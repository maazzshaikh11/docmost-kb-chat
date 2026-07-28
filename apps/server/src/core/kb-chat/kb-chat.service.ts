import { Injectable, Logger, ServiceUnavailableException } from '@nestjs/common';
import { InjectKysely } from 'nestjs-kysely';
import { KyselyDB } from '@docmost/db/types/kysely.types';

/** Internal format from the Python RAG service */
interface RagSource {
  title: string;
  article_id: string | null;
  source_url: string | null;
  section: string | null;
}

interface RagResponse {
  answer: string;
  sources: RagSource[];
  chunks_used: number;
  model: string;
}

/** External format for frontend */
export interface KbSource {
  pageId: string;
  title: string;
  slugId: string;
  spaceSlug: string | null;
  similarity: number;
  matchedText: string | null;
}

export interface KbChatResult {
  answer: string;
  sources: KbSource[];
}

@Injectable()
export class KbChatService {
  private readonly logger = new Logger(KbChatService.name);

  /** Base URL of the Python RAG microservice (rag_server.py). */
  private readonly ragServiceUrl: string;

  constructor(
    @InjectKysely() private readonly db: KyselyDB,
  ) {
    // Allow override via env var; default to local dev port
    this.ragServiceUrl = process.env.KB_CHAT_SERVICE_URL ?? 'http://localhost:8765';
  }

  async query(userQuery: string, topK = 5): Promise<KbChatResult> {
    const url = `${this.ragServiceUrl}/query`;

    this.logger.debug(`Forwarding KB query to ${url}: "${userQuery.slice(0, 80)}"`);

    let response: Response;
    try {
      response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: userQuery, top_k: topK }),
        signal: AbortSignal.timeout(130_000), // 130 s – longer than Ollama's 120 s
      });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      this.logger.error(`RAG service unreachable: ${msg}`);
      throw new ServiceUnavailableException(
        'The KB search service is currently unavailable. Please try again later.',
      );
    }

    if (!response.ok) {
      const body = await response.text().catch(() => '');
      this.logger.error(`RAG service returned ${response.status}: ${body.slice(0, 200)}`);
      throw new ServiceUnavailableException(
        `KB search service error (HTTP ${response.status}).`,
      );
    }

    const ragData = (await response.json()) as RagResponse;
    this.logger.debug(
      `RAG response: chunks_used=${ragData.chunks_used} model=${ragData.model} sources=${ragData.sources.length}`,
    );

    // Map RAG sources to Docmost pages
    const sources = await this.mapSourcesToPages(ragData.sources);

    return {
      answer: ragData.answer,
      sources,
    };
  }

  /**
   * Map RAG sources (with external article titles) to actual Docmost pages.
   * Extracts the slugified title from source_url and matches against Docmost page titles.
   * RESTRICTED TO NEWSPACE ONLY to avoid matching pages from old imported spaces.
   * Example URL: https://support.contactsplus.com/hc/en-us/articles/4406997651099-Contacts-for-iOS
   * Extracts: "Contacts-for-iOS"
   */
  private async mapSourcesToPages(ragSources: RagSource[]): Promise<KbSource[]> {
    const mappedSources: KbSource[] = [];
    const targetSpaceSlug = 'newspace'; // Restrict to NewSpace only

    for (const source of ragSources) {
      try {
        let searchTitle = source.title;
        
        // If source_url is available, extract the slugified title from it
        // URL format: .../articles/ARTICLE_ID-Slugified-Title
        if (source.source_url) {
          const match = source.source_url.match(/articles\/\d+-(.+)$/);
          if (match && match[1]) {
            searchTitle = match[1];
            this.logger.debug(`Extracted slug from URL: "${searchTitle}" from "${source.source_url}"`);
          }
        }

        // Look up page by title (case-insensitive exact or partial match)
        // First try exact match, then fallback to partial
        // RESTRICTED TO NEWSPACE
        let page = await this.db
          .selectFrom('pages')
          .innerJoin('spaces', 'spaces.id', 'pages.spaceId')
          .select([
            'pages.id as pageId',
            'pages.slugId',
            'pages.title',
            'spaces.slug as spaceSlug',
          ])
          .where('pages.title', '=', searchTitle)
          .where('spaces.slug', '=', targetSpaceSlug)
          .where('pages.deletedAt', 'is', null)
          .executeTakeFirst();

        // If no exact match, try case-insensitive partial match
        if (!page) {
          page = await this.db
            .selectFrom('pages')
            .innerJoin('spaces', 'spaces.id', 'pages.spaceId')
            .select([
              'pages.id as pageId',
              'pages.slugId',
              'pages.title',
              'spaces.slug as spaceSlug',
            ])
            .where('pages.title', 'ilike', `%${searchTitle}%`)
            .where('spaces.slug', '=', targetSpaceSlug)
            .where('pages.deletedAt', 'is', null)
            .executeTakeFirst();
        }

        if (page) {
          this.logger.debug(
            `Mapped source "${source.title}" to page: pageId=${page.pageId}, slugId=${page.slugId}, spaceSlug=${page.spaceSlug}`,
          );
          
          mappedSources.push({
            pageId: page.pageId,
            title: page.title || source.title,
            slugId: page.slugId,
            spaceSlug: page.spaceSlug,
            similarity: 1.0,
            matchedText: source.section || null,
          });
        } else {
          this.logger.warn(`No Docmost page found in ${targetSpaceSlug} for RAG source: "${source.title}" (searched for: "${searchTitle}")`);
        }
      } catch (err) {
        this.logger.error(`Error mapping source "${source.title}": ${err}`);
      }
    }

    this.logger.debug(`Mapped ${mappedSources.length} of ${ragSources.length} sources to Docmost pages in ${targetSpaceSlug}`);
    return mappedSources;
  }
}
