#!/usr/bin/env python3
"""
Knowledge Base Chat CLI (Semantic Search Version).

Retrieves relevant KB chunks and prints them (No Ollama).
"""

import argparse
import json
import os
import pickle
import re
from pathlib import Path

import faiss
import numpy as np
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer

# ---------------------------------------------------------------------------
# Configuration Constants
# ---------------------------------------------------------------------------

# Article reranking parameters
FAISS_CANDIDATES = 15           # Number of chunks to retrieve for reranking
ARTICLE_BONUS_WEIGHT = 0.3      # Weight applied to bonus chunks in aggregate score
MAX_BONUS_CHUNKS = 2            # Maximum number of bonus chunks to consider per article

# Debug output control
DEBUG_RAG = False               # Set to True to enable detailed ranking debug output


def _clean_text(text: str) -> str:
    """
    Clean and format text for display in the chat UI.
    
    - Fix inline numbered items (split mid-sentence numbers to new lines)
    - Strip heading markers but keep the text
    - Normalize list formatting to consistent style
    - Bold important UI terms
    - Preserve list and paragraph structure
    - Remove metadata artifacts
    - Strip leading heading if present
    """
    import re
    
    # Remove metadata artifacts that might appear inline
    text = re.sub(r'(?i)article\s+id\s*:\s*\S+', '', text)
    text = re.sub(r'(?i)source\s+url\s*:\s*\S+', '', text)
    text = re.sub(r'(?i)section\s*:\s*\S+', '', text)
    
    # FIX 1: Split inline numbered items that don't start on their own line
    # Pattern: sentence-ending punctuation + whitespace + number. + capital letter
    # Example: "...Firefox, Safari, Edge, and Opera. 2. Create your Contacts+ account"
    # Becomes: "...Firefox, Safari, Edge, and Opera.\n\n2. Create your Contacts+ account"
    text = re.sub(r'([.:])\s+(\d+)\.\s+([A-Z])', r'\1\n\n\2. \3', text)
    
    lines = text.splitlines()
    out = []
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        
        if not stripped:
            out.append('')
            continue
        
        # Remove heading markers (##, ###, etc.) but keep the text
        if stripped.startswith('#'):
            heading_text = re.sub(r'^#+\s*', '', stripped).strip()
            # Strip leading heading entirely (redundant with sources panel)
            if i == 0 or (i == 1 and not lines[0].strip()):
                continue
            stripped = heading_text
        
        # Normalize list markers: convert * to - for bullets
        list_match = re.match(r'^(\s*)(\*|\-|\d+\.)\s+(.+)$', stripped)
        if list_match:
            indent, marker, content = list_match.groups()
            if marker == '*':
                marker = '-'
            stripped = f"{indent}{marker} {content}"
        
        # Ensure blank lines around lists
        is_list = bool(re.match(r'^\s*([-*]|\d+\.)\s', stripped))
        prev_blank = (not out) or out[-1] == ''
        
        if is_list and not prev_blank:
            out.append('')
        
        out.append(stripped)
        
        # Blank line after last item in a list block
        if is_list and i + 1 < len(lines):
            next_line = lines[i + 1].strip()
            next_is_list = bool(re.match(r'^\s*([-*]|\d+\.)\s', next_line))
            if not next_is_list and next_line:
                out.append('')
    
    # Collapse multiple blank lines to at most 2
    result = re.sub(r'\n{3,}', '\n\n', '\n'.join(out))
    
    # FIX 2: Bold important UI terms (apply as final pass)
    ui_terms = [
        'My Contacts', 'Sync Sources', 'Add Sync Source', 'Google', 'Settings',
        'Contacts+', 'Google Contacts', 'Account Settings', 'Profile Settings',
        'Preferences', 'Menu', 'Dashboard', 'Home', 'Save', 'Cancel', 'Edit',
        'Delete', 'Add', 'Remove', 'Import', 'Export', 'Sync', 'Refresh',
        'Sign In', 'Sign Out', 'Log In', 'Log Out', 'Register', 'Password',
        'Email', 'Username', 'Profile', 'Account', 'Contact List', 'Groups',
        'Tags', 'Labels', 'Search', 'Filter', 'Sort', 'View', 'More Options',
        'Help', 'Support', 'FAQ', 'Documentation', 'Tutorial', 'Guide',
    ]
    
    for term in ui_terms:
        # Match whole words only, avoid double-bolding
        pattern = r'(?<!\*\*)(?<!\w)(' + re.escape(term) + r')(?!\w)(?!\*\*)'
        result = re.sub(pattern, r'**\1**', result, flags=re.IGNORECASE)
    
    # Clean up any double-bolding that might have occurred
    result = re.sub(r'\*\*\*\*+', '**', result)
    
    return result.strip()


class KBChat:
    """Chat interface for knowledge base queries."""
    
    def __init__(self, index_dir: str = "output/kb_index", debug: bool = False):
        self.index_dir = Path(index_dir)
        self.debug = debug
        
        # Load environment variables from project root .env
        project_root = Path(__file__).parent.parent.parent
        dotenv_path = project_root / ".env"
        load_dotenv(dotenv_path)
        
        # Load configuration
        config_path = self.index_dir / "config.json"
        if not config_path.exists():
            raise FileNotFoundError(f"Index not found at {self.index_dir}. Run kb_indexer.py first.")
        
        with open(config_path) as f:
            self.config = json.load(f)
        
        # Load sentence-transformers for embeddings
        embedding_model_name = self.config.get('embedding_model', 'all-MiniLM-L6-v2')
        if self.debug:
            print(f"Loading embedding model: {embedding_model_name}")
        self.embedding_model = SentenceTransformer(embedding_model_name)
        
        # Load FAISS index
        index_path = self.index_dir / "faiss.index"
        self.index = faiss.read_index(str(index_path))
        
        # Load chunks
        chunks_path = self.index_dir / "chunks.pkl"
        with open(chunks_path, 'rb') as f:
            self.chunks = pickle.load(f)
        
        if self.debug:
            print(f"Loaded index with {self.index.ntotal} vectors")
            print(f"Loaded {len(self.chunks)} chunks")
    
    def generate_embedding(self, text: str) -> np.ndarray:
        """Generate embedding using sentence-transformers."""
        embedding = self.embedding_model.encode(text, convert_to_numpy=True)
        return embedding.astype(np.float32)
    
    def retrieve(self, query: str, top_k: int = 5) -> list[dict]:
        """Retrieve top-k most relevant chunks."""
        # Internally retrieve more candidates for article-level reranking
        retrieval_k = max(top_k * 3, FAISS_CANDIDATES)
        
        # Generate query embedding
        query_embedding = self.generate_embedding(query)
        query_embedding = query_embedding.reshape(1, -1)
        
        # Normalize for cosine similarity
        faiss.normalize_L2(query_embedding)
        
        # Search
        scores, indices = self.index.search(query_embedding, retrieval_k)
        
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < len(self.chunks):
                chunk = self.chunks[idx].copy()
                chunk['score'] = float(score)
                chunk["chunk_idx"] = int(idx)
                results.append(chunk)
        
        return results
    
    def rerank_by_article(self, chunks: list[dict]) -> list[str]:
        """
        Rerank articles based on aggregate chunk scores.
        
        Groups chunks by article and computes aggregate score:
        agg_score = best_score + ARTICLE_BONUS_WEIGHT * sum(next MAX_BONUS_CHUNKS scores)
        
        This rewards articles with multiple relevant chunks without letting
        many mediocre chunks accumulate excessive bonus.
        
        Returns: List of article keys ordered by aggregate score descending
        """
        from collections import defaultdict
        
        # Group chunks by article
        articles = defaultdict(list)
        
        for chunk in chunks:
            meta = chunk["metadata"]
            article_id = meta.get("article_id")
            source_url = meta.get("source_url")
            title = meta.get("title", "Unknown Article")
            
            # Use same deduplication key as format_results
            key = article_id if article_id else (source_url if source_url else title)
            articles[key].append(chunk)
        
        # Compute aggregate score for each article
        article_scores = {}
        
        for key, article_chunks in articles.items():
            # Sort chunks by score descending
            sorted_chunks = sorted(article_chunks, key=lambda c: c["score"], reverse=True)
            sorted_scores = [c["score"] for c in sorted_chunks]
            
            best_score = sorted_scores[0]
            # Cap bonus to only next MAX_BONUS_CHUNKS highest-scoring chunks
            bonus_chunks = sorted_scores[1:MAX_BONUS_CHUNKS + 1]
            
            # Aggregate: best + ARTICLE_BONUS_WEIGHT * sum(next N)
            agg_score = best_score + ARTICLE_BONUS_WEIGHT * sum(bonus_chunks)
            article_scores[key] = agg_score
        
        # Return article keys sorted by aggregate score
        ranked_keys = sorted(article_scores.keys(), 
                            key=lambda k: article_scores[k], 
                            reverse=True)
        
        return ranked_keys
    
    def format_results(self, context_chunks: list[dict], query: str = None) -> dict:
        """
        Format chunks as semantic search results.
        
        Strategy:
        1. Rerank by article (aggregate scores across chunks)
        2. Return highest-ranked article's best chunk as main answer
        3. Only merge an adjacent chunk if:
           - It's also in the top-k retrieved results (independently retrieved), OR
           - Its similarity to the query is within 0.05 of the top chunk's score
        4. Next 2 unique articles go in sources only (not concatenated to answer)
        5. Do not merge unrelated chunks or chunks from different articles
        """
        if not context_chunks:
            return {'answer': '', 'sources': [], 'num_tokens': 0}
        
        # Rerank articles by aggregate score
        ranked_article_keys = self.rerank_by_article(context_chunks)
        
        # Group chunks by article for easy lookup
        from collections import defaultdict
        articles = defaultdict(list)
        
        for chunk in context_chunks:
            meta = chunk['metadata']
            article_id = meta.get('article_id')
            source_url = meta.get('source_url')
            title = meta.get('title', 'Unknown Article')
            key = article_id if article_id else (source_url if source_url else title)
            articles[key].append(chunk)
        
        # Sort chunks within each article by score
        for key in articles:
            articles[key] = sorted(articles[key], key=lambda c: c.get('score', 0), reverse=True)
        
        # Get the top-ranked article's best chunk
        if not ranked_article_keys:
            return {'answer': '', 'sources': [], 'num_tokens': 0}
        
        top_article_key = ranked_article_keys[0]
        top_chunk = articles[top_article_key][0]  # Best chunk from top article
        top_score = top_chunk.get('score', 0)
        top_idx = top_chunk.get('chunk_idx')
        
        # Collect chunk indices that are in the retrieved results
        retrieved_indices = {c.get('chunk_idx') for c in context_chunks if c.get('chunk_idx') is not None}
        
        # Check if we should include adjacent chunks
        answer_chunks = [top_chunk]
        
        if top_idx is not None:
            # Check preceding chunk
            if top_idx - 1 >= 0:
                prev_chunk = self.chunks[top_idx - 1]
                prev_meta = prev_chunk['metadata']
                prev_article_id = prev_meta.get('article_id')
                prev_source_url = prev_meta.get('source_url')
                prev_title = prev_meta.get('title', 'Unknown Article')
                prev_key = prev_article_id if prev_article_id else (prev_source_url if prev_source_url else prev_title)
                
                # Only include if same article AND (independently retrieved OR high similarity)
                if prev_key == top_article_key:
                    should_include = False
                    
                    # Check if independently retrieved
                    if (top_idx - 1) in retrieved_indices:
                        should_include = True
                    # Check similarity threshold (within 0.05 of top score)
                    elif query:
                        prev_embedding = self.generate_embedding(prev_chunk['text'])
                        prev_embedding = prev_embedding.reshape(1, -1)
                        faiss.normalize_L2(prev_embedding)
                        query_embedding = self.generate_embedding(query)
                        query_embedding = query_embedding.reshape(1, -1)
                        faiss.normalize_L2(query_embedding)
                        prev_score = float(np.dot(prev_embedding, query_embedding.T)[0, 0])
                        if abs(prev_score - top_score) <= 0.05:
                            should_include = True
                    
                    if should_include:
                        answer_chunks.insert(0, prev_chunk)
            
            # Check following chunk
            if top_idx + 1 < len(self.chunks):
                next_chunk = self.chunks[top_idx + 1]
                next_meta = next_chunk['metadata']
                next_article_id = next_meta.get('article_id')
                next_source_url = next_meta.get('source_url')
                next_title = next_meta.get('title', 'Unknown Article')
                next_key = next_article_id if next_article_id else (next_source_url if next_source_url else next_title)
                
                # Only include if same article AND (independently retrieved OR high similarity)
                if next_key == top_article_key:
                    should_include = False
                    
                    # Check if independently retrieved
                    if (top_idx + 1) in retrieved_indices:
                        should_include = True
                    # Check similarity threshold (within 0.05 of top score)
                    elif query:
                        next_embedding = self.generate_embedding(next_chunk['text'])
                        next_embedding = next_embedding.reshape(1, -1)
                        faiss.normalize_L2(next_embedding)
                        query_embedding = self.generate_embedding(query)
                        query_embedding = query_embedding.reshape(1, -1)
                        faiss.normalize_L2(query_embedding)
                        next_score = float(np.dot(next_embedding, query_embedding.T)[0, 0])
                        if abs(next_score - top_score) <= 0.05:
                            should_include = True
                    
                    if should_include:
                        answer_chunks.append(next_chunk)
        
        # Merge answer chunks (remove overlap between adjacent chunks)
        merged_text = answer_chunks[0]['text'].strip()
        for i in range(1, len(answer_chunks)):
            curr_text = answer_chunks[i]['text'].strip()
            
            # Try to detect overlap at the boundary
            overlap_len = 0
            max_overlap = min(400, len(merged_text), len(curr_text))
            for size in range(max_overlap, 20, -1):
                if merged_text.endswith(curr_text[:size]):
                    overlap_len = size
                    break
            
            if overlap_len > 0:
                merged_text += curr_text[overlap_len:]
            else:
                merged_text += "\n\n" + curr_text
        
        # Clean the answer text
        answer_text = _clean_text(merged_text)
        
        # Build sources list: top 3 articles from reranked list
        sources = []
        source_map = {}
        
        for key in ranked_article_keys[:3]:
            if key in articles:
                chunk = articles[key][0]  # Get representative chunk for metadata
                meta = chunk['metadata']
                title = meta.get('title', 'Unknown Article')
                article_id = meta.get('article_id')
                source_url = meta.get('source_url')
                section = meta.get('section')
                
                sources.append({
                    'title': title,
                    'article_id': article_id,
                    'source_url': source_url,
                    'section': section,
                })
                source_map[key] = len(sources)
        
        # Add citation for the top article only
        if top_article_key in source_map:
            citation_num = source_map[top_article_key]
            answer_text += f"\n\n[{citation_num}]"
        
        return {
            'answer': answer_text,
            'sources': sources,
            'num_tokens': 0,
        }
    
    def chat(self, query: str, top_k: int = 5):
        """Process a chat query."""
        print(f"\n{'='*80}")
        print(f"QUESTION: {query}")
        print(f"{'='*80}\n")
        
        # Retrieve relevant chunks
        if self.debug:
            print("Retrieving relevant chunks...\n")
        
        retrieved = self.retrieve(query, top_k=top_k)
        
        # DEBUG: Print rankings if enabled
        if DEBUG_RAG:
            from collections import defaultdict
            
            print("\n" + "="*80)
            print("Raw FAISS ranking:")
            print("="*80)
            for i, r in enumerate(retrieved[:10]):
                print(f"{i+1}. {r['metadata'].get('title', 'Unknown')[:50]:50s}  score={r['score']:.4f}")
            
            # Compute article scores for debug output
            articles = defaultdict(list)
            for chunk in retrieved:
                meta = chunk['metadata']
                article_id = meta.get('article_id')
                source_url = meta.get('source_url')
                title = meta.get('title', 'Unknown Article')
                key = article_id if article_id else (source_url if source_url else title)
                articles[key].append(chunk)
            
            article_scores = {}
            for key, article_chunks in articles.items():
                sorted_chunks = sorted(article_chunks, key=lambda c: c['score'], reverse=True)
                sorted_scores = [c['score'] for c in sorted_chunks]
                best_score = sorted_scores[0]
                bonus_chunks = sorted_scores[1:MAX_BONUS_CHUNKS + 1]
                agg_score = best_score + ARTICLE_BONUS_WEIGHT * sum(bonus_chunks)
                article_scores[key] = {
                    'score': agg_score,
                    'title': sorted_chunks[0]['metadata'].get('title', 'Unknown'),
                    'num_chunks': len(article_chunks),
                    'best': best_score,
                    'bonus': bonus_chunks,
                    'all_scores': sorted_scores[:5]
                }
            
            print("\n" + "="*80)
            print("Article reranking:")
            print("="*80)
            ranked = sorted(article_scores.items(), key=lambda x: x[1]['score'], reverse=True)
            for i, (key, info) in enumerate(ranked[:10]):
                bonus_str = f"[{', '.join(f'{s:.3f}' for s in info['bonus'])}]" if info['bonus'] else "[]"
                print(f"{i+1}. {info['title'][:45]:45s}  agg={info['score']:.4f}")
                print(f"   best={info['best']:.4f} + {ARTICLE_BONUS_WEIGHT}*{bonus_str} | {info['num_chunks']} chunks | top5={[f'{s:.3f}' for s in info['all_scores']]}")
            print("="*80 + "\n")
        
        if self.debug:
            print("TOP RETRIEVED CHUNKS (DETAILED):")
            print("-" * 80)
            for i, chunk in enumerate(retrieved):
                title = chunk['metadata'].get('title', 'Unknown')
                score = chunk['score']
                preview = chunk['text'][:150].replace('\n', ' ')
                print(f"{i+1}. [{score:.4f}] {title}")
                print(f"   {preview}...")
                print()
            print("-" * 80)
            print()
        
        if not retrieved:
            print("No relevant information found in the knowledge base.")
            return
        
        # Format answer
        if self.debug:
            print("Formatting results...\n")
        
        try:
            result = self.format_results(retrieved, query=query)
            
            print("ANSWER (SEARCH RESULTS):")
            print("-" * 80)
            print(result['answer'])
            print("-" * 80)
            print()
            
            print("SOURCES:")
            for source in result['sources']:
                title = source['title']
                url = source.get('source_url', 'N/A')
                section = source.get('section', 'N/A')
                print(f"  • {title}")
                print(f"    Section: {section}")
                print(f"    URL: {url}")
                print()
            
            if self.debug:
                print(f"Tokens used: {result['num_tokens']}")
        
        except Exception as e:
            print(f"Error formatting results: {e}")
            if self.debug:
                import traceback
                traceback.print_exc()


def main():
    parser = argparse.ArgumentParser(description="Chat with KB using RAG")
    parser.add_argument(
        "query",
        type=str,
        help="Question to ask",
    )
    parser.add_argument(
        "--index-dir",
        type=str,
        default="output/kb_index",
        help="Directory containing the index",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Number of chunks to retrieve",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Show debug information including retrieval scores",
    )
    
    args = parser.parse_args()
    
    try:
        chat = KBChat(index_dir=args.index_dir, debug=args.debug)
        chat.chat(args.query, top_k=args.top_k)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        return 1
    except Exception as e:
        print(f"Error: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
