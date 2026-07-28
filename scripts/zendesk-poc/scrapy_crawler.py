#!/usr/bin/env python3
"""
Scrapy-based web crawler for Contacts+ Help Center.

Architecture:
  Scrapy = crawling, discovery, deduplication, scheduling, callbacks
  requests (via middleware) = actual HTTP transport
  BeautifulSoup = HTML parsing and extraction (html.parser)
  migrate_article.py functions = cleaning, images, embeds, ZIP creation

Root cause of 403 (diagnosed):
  A transport or client-specific 403 error occurs when using Scrapy's native
  Twisted async HTTP client. In contrast, using Python's requests/urllib3
  library with browser-compatible headers returns HTTP 200.

  Secondary causes that were also fixed:
  1. Scrapy's DefaultHeadersMiddleware overrides per-request headers; all
     browser headers must be set via DEFAULT_REQUEST_HEADERS.
  2. Including 'br' (Brotli) in Accept-Encoding: Scrapy cannot decode Brotli.
  3. Scrapy 2.13+ replaced start_requests() with async def start().

Fix: Scrapy Downloader Middleware intercepts each Request and delegates it to
a persistent requests.Session() with full browser headers. Scrapy still owns
all crawl logic: deduplication, scheduling, retries, callbacks, depth control.
This is NOT switching to requests+BeautifulSoup — Scrapy is still the crawler.

Crawl flow:
  https://support.contactsplus.com/hc/en-us  (homepage)
    → discover section links (/sections/...)
    → follow each section page (handle pagination if present)
    → collect article links (/articles/...)
    → deduplicate with Scrapy's built-in duplicate filter
    → process only the 3 POC article IDs
"""

import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse
from typing import AsyncIterator, Any

import requests as req
import scrapy
from bs4 import BeautifulSoup
from scrapy.crawler import CrawlerProcess
from scrapy.http import HtmlResponse, Request

# Import transformation functions from existing migration script.
# These are verified working — do NOT rewrite them.
from migrate_article import (
    clean_html,
    download_images,
    extract_remote_images,
    rewrite_image_sources,
    sanitize_filename,
    build_docmost_html,
    create_zip,
)

BASE_URL = "https://support.contactsplus.com"
START_URL = f"{BASE_URL}/hc/en-us"

# POC: process only these 3 article IDs even if more are discovered
POC_ARTICLE_IDS = {
    "4407286476827",  # image-heavy (Using Zapier and Contacts+)
    "4406997562651",  # list/link-heavy (Contacts+ for Web)
    "4410672626203",  # Loom embeds (Getting Started)
}

# Full browser-compatible request headers.
# Accept-Encoding deliberately omits 'br' (Brotli) because Scrapy's
# HttpCompressionMiddleware cannot decode it (this middleware is disabled
# anyway since we handle transport via requests, but kept explicit for clarity).
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",  # No 'br' — requests handles gzip natively
    "Cache-Control": "max-age=0",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


# =========================================================================== #
# Downloader Middleware: bridges Scrapy's crawl engine to requests.Session()   #
# =========================================================================== #

class RequestsTransportMiddleware:
    """
    Scrapy Downloader Middleware that intercepts every HTTP request and
    executes it using requests.Session() instead of Scrapy's Twisted client.

    This addresses a transport/client-specific 403 response encountered when
    fetching public pages via Scrapy's native Twisted client, whereas Python's
    requests/urllib3 library with browser-compatible headers receives HTTP 200.

    Scrapy still owns all crawl logic (scheduling, deduplication, depth
    control, callbacks). Only the raw HTTP transport is delegated here.
    """

    def __init__(self):
        self.session = req.Session()
        self.session.headers.update(BROWSER_HEADERS)
        self.crawler = None

    @classmethod
    def from_crawler(cls, crawler):
        mw = cls()
        mw.crawler = crawler
        return mw

    def process_request(self, request, spider=None):
        """Execute Scrapy request via requests.Session; return HtmlResponse."""
        actual_spider = spider or getattr(self, "crawler", None) and self.crawler.spider
        try:
            response = self.session.get(
                request.url,
                timeout=30,
                allow_redirects=True,
            )
        except req.RequestException as exc:
            if actual_spider:
                actual_spider.logger.error(
                    f"HTTP transport error for {request.url}: {exc}"
                )
            raise

        return HtmlResponse(
            url=response.url,
            status=response.status_code,
            headers=dict(response.headers),
            body=response.content,
            encoding="utf-8",
            request=request,
        )


# =========================================================================== #
# Spider                                                                        #
# =========================================================================== #

class ContactsPlusSpider(scrapy.Spider):
    """
    Crawls Contacts+ Help Center starting from the homepage.

    Discovery path:
      homepage → section links → (paginated) article links → article pages

    Only processes the 3 POC article IDs defined in POC_ARTICLE_IDS.
    """

    name = "contactsplus"
    allowed_domains = ["support.contactsplus.com"]

    custom_settings = {
        # Disable Scrapy's own HTTP cache and compression middleware —
        # we handle all HTTP via RequestsTransportMiddleware.
        "HTTPCACHE_ENABLED": False,

        # Disable middlewares that conflict with RequestsTransportMiddleware.
        # The requests library handles compression, redirects, and cookies.
        "DOWNLOADER_MIDDLEWARES": {
            # Disable Scrapy's transport-layer middlewares
            "scrapy.downloadermiddlewares.httpcompression.HttpCompressionMiddleware": None,
            "scrapy.downloadermiddlewares.useragent.UserAgentMiddleware": None,
            "scrapy.downloadermiddlewares.defaultheaders.DefaultHeadersMiddleware": None,
            "scrapy.downloadermiddlewares.redirect.RedirectMiddleware": None,
            "scrapy.downloadermiddlewares.cookies.CookiesMiddleware": None,
            # Insert our requests-based transport middleware
            f"{__name__}.RequestsTransportMiddleware": 543,
        },

        # Polite crawl: 1 request at a time with a delay
        "CONCURRENT_REQUESTS": 1,
        "DOWNLOAD_DELAY": 1.5,

        # Disable retries (requests handles transport; Scrapy retry would
        # re-issue via Twisted which has the fingerprint problem)
        "RETRY_ENABLED": False,

        # Obey robots.txt - verify compliance with site-defined policies
        "ROBOTSTXT_OBEY": True,

        "LOG_LEVEL": "INFO",
    }

    def __init__(self, output_dir: str = "output/scrapy", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.discovered_sections: set[str] = set()
        self.discovered_articles: set[str] = set()
        self.processed_results: list[dict] = []

    # ------------------------------------------------------------------ #
    # Spider entry point — Scrapy 2.13+ async start()                      #
    # ------------------------------------------------------------------ #

    async def start(self) -> AsyncIterator[Any]:
        """Start crawl from the Help Center homepage."""
        self.logger.info(f"Starting crawl from: {START_URL}")
        yield Request(START_URL, callback=self.parse_homepage)

    # ------------------------------------------------------------------ #
    # Page parsers                                                          #
    # ------------------------------------------------------------------ #

    def parse(self, response):
        """Default parse method (required by Scrapy; not used directly)."""
        pass

    def parse_homepage(self, response):
        """Parse homepage: discover all section links."""
        self.logger.info(
            f"Parsing homepage: {response.url} (HTTP {response.status})"
        )

        if response.status != 200:
            self.logger.error(
                f"Homepage returned HTTP {response.status}. "
                "Cannot proceed with discovery."
            )
            return

        # html.parser verified to work better than lxml for this site
        soup = BeautifulSoup(response.text, "html.parser")

        section_links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/sections/" in href:
                full_url = urljoin(BASE_URL, href)
                if full_url not in self.discovered_sections:
                    self.discovered_sections.add(full_url)
                    section_links.append(full_url)

        self.logger.info(
            f"Discovered {len(section_links)} sections on homepage:"
        )
        for url in section_links:
            label = url.split("/sections/")[1] if "/sections/" in url else url
            self.logger.info(f"  {label}")
            yield Request(url, callback=self.parse_section)

    def parse_section(self, response):
        """Parse a section page: collect article links and follow pagination."""
        self.logger.info(
            f"Parsing section: {response.url} (HTTP {response.status})"
        )

        if response.status != 200:
            self.logger.warning(
                f"Section {response.url} returned HTTP {response.status}"
            )
            return

        soup = BeautifulSoup(response.text, "html.parser")

        found_on_page = 0
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/articles/" in href:
                full_url = urljoin(BASE_URL, href)
                parsed = urlparse(full_url)
                # Canonical URL: strip query string and fragment
                canonical = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

                if canonical not in self.discovered_articles:
                    self.discovered_articles.add(canonical)
                    found_on_page += 1

                    article_id = self._extract_article_id(canonical)
                    if article_id in POC_ARTICLE_IDS:
                        self.logger.info(
                            f"  *** POC article queued: {article_id}"
                        )
                        yield Request(canonical, callback=self.parse_article)

        self.logger.info(
            f"  {found_on_page} new articles found "
            f"(total discovered: {len(self.discovered_articles)})"
        )

        # Follow pagination if present
        next_page = self._find_next_page(soup, response.url)
        if next_page:
            self.logger.info(f"  Following pagination: {next_page}")
            yield Request(next_page, callback=self.parse_section)

    def parse_article(self, response):
        """Parse article page; transform to Docmost ZIP format."""
        article_url = response.url
        article_id = self._extract_article_id(article_url)

        self.logger.info(
            f"Parsing article {article_id}: {article_url} (HTTP {response.status})"
        )

        if response.status != 200:
            self.logger.error(
                f"Article {article_id} returned HTTP {response.status}"
            )
            self.processed_results.append({
                "article_id": article_id,
                "url": article_url,
                "status": "error",
                "error": f"HTTP {response.status}",
            })
            return

        # html.parser — verified to work better than lxml for this site
        soup = BeautifulSoup(response.text, "html.parser")

        title = self._extract_title(soup)
        section_info = self._extract_section_info(soup)
        article_body_html = self._extract_article_body(soup)

        if not article_body_html:
            self.logger.warning(
                f"No article body found for {article_id} — skipping"
            )
            self.processed_results.append({
                "article_id": article_id,
                "url": article_url,
                "status": "error",
                "error": "No article body found in HTML",
            })
            return

        self.logger.info(f"  Title: {title}")
        self.logger.info(f"  Body HTML length: {len(article_body_html)} chars")
        self.logger.info(
            f"  Section: {section_info.get('section_name')} "
            f"/ Category: {section_info.get('category_name')}"
        )

        metadata = {
            "article_id": article_id,
            "title": title,
            "source_url": article_url,
            "section_id": section_info.get("section_id"),
            "section_name": section_info.get("section_name"),
            "category_name": section_info.get("category_name"),
            "updated_at": None,  # Not exposed in public HTML
        }

        result = self._process_article(article_id, title, article_body_html, metadata)
        self.processed_results.append(result)

    # ------------------------------------------------------------------ #
    # HTML extraction helpers                                               #
    # ------------------------------------------------------------------ #

    def _extract_article_id(self, url: str) -> str | None:
        m = re.search(r"/articles/(\d+)", url)
        return m.group(1) if m else None

    def _extract_title(self, soup: BeautifulSoup) -> str:
        for tag, attrs in [
            ("h1", {"class": "article-title"}),
            ("h1", {}),
        ]:
            el = soup.find(tag, attrs)
            if el:
                text = el.get_text(strip=True)
                if text:
                    return text

        title_tag = soup.find("title")
        if title_tag:
            text = title_tag.get_text(strip=True)
            if "|" in text:
                text = text.split("|")[0].strip()
            if text:
                return text

        return "Untitled Article"

    def _extract_section_info(self, soup: BeautifulSoup) -> dict:
        info = {"section_id": None, "section_name": None, "category_name": None}

        breadcrumbs = soup.find("nav", {"aria-label": "Breadcrumb"}) or soup.find(
            "ol", {"class": "breadcrumbs"}
        )
        if breadcrumbs:
            links = breadcrumbs.find_all("a")
            if len(links) >= 2:
                info["category_name"] = links[1].get_text(strip=True)
                info["section_name"] = links[-1].get_text(strip=True)
                m = re.search(r"/sections/(\d+)", links[-1].get("href", ""))
                if m:
                    info["section_id"] = m.group(1)

        return info

    def _extract_article_body(self, soup: BeautifulSoup) -> str:
        """Extract article body HTML. Zendesk HC uses <div class='article-body'>."""
        for tag, attrs in [
            ("div", {"class": "article-body"}),
            ("article", {}),
            ("div", {"class": "article-content"}),
            ("section", {"class": "article-info"}),
        ]:
            el = soup.find(tag, attrs)
            if el:
                return str(el)
        return ""

    def _find_next_page(self, soup: BeautifulSoup, current_url: str) -> str | None:
        """Return the next pagination URL if present, else None."""
        next_link = soup.find("a", rel="next")
        if not next_link:
            next_link = soup.find(
                "a", {"class": lambda c: c and "next-page" in c}
            )
        if next_link and next_link.get("href"):
            return urljoin(BASE_URL, next_link["href"])
        return None

    def _absolutize_urls(self, html: str) -> str:
        """
        Rewrite relative img src and a href URLs to absolute URLs.

        Zendesk HC serves images with paths like /hc/article_attachments/...
        which are relative to the site root. extract_remote_images() in
        migrate_article.py only processes absolute http(s):// URLs, so we
        must absolutize before calling clean_html().
        """
        soup = BeautifulSoup(html, "html.parser")
        for img in soup.find_all("img", src=True):
            src = img["src"]
            if src.startswith("/"):
                img["src"] = BASE_URL + src
            elif not src.startswith(("http://", "https://")):
                img["src"] = urljoin(BASE_URL + "/hc/en-us/", src)
        return str(soup)

    # ------------------------------------------------------------------ #
    # Article transformation (reuses migrate_article.py verbatim)          #
    # ------------------------------------------------------------------ #

    def _process_article(
        self,
        article_id: str,
        title: str,
        body_html: str,
        metadata: dict,
    ) -> dict:
        """
        Transform article HTML → Docmost Generic ZIP Import format.

        Reuses from migrate_article.py (not modified):
          clean_html()            — strip scripts/styles; convert Loom/YT/Vimeo
                                    iframes to Docmost <div data-type="embed">
          extract_remote_images() — find img src URLs in cleaned HTML
          download_images()       — download images; infer extension from MIME
          rewrite_image_sources() — replace remote URLs with local asset paths
          build_docmost_html()    — wrap in DOCTYPE + metadata comment header
          create_zip()            — bundle HTML + assets into ZIP Import archive
        """
        self.logger.info(f"Processing article {article_id}: {title}")

        # 0. Absolutize relative image URLs before processing
        #    (Zendesk serves images as /hc/article_attachments/... paths)
        body_html = self._absolutize_urls(body_html)

        # 1. Clean HTML
        cleaned_body, clean_stats = clean_html(body_html)
        self.logger.info(
            f"  Loom embeds converted: {clean_stats.get('loom_embeds', 0)}"
        )
        self.logger.info(
            f"  Unsupported iframes: {clean_stats.get('unsupported_iframes', 0)}"
        )

        # 2. Download images
        image_urls = extract_remote_images(cleaned_body)
        self.logger.info(f"  Images found: {len(image_urls)}")

        article_dir = self.output_dir / sanitize_filename(title)
        assets_dir = article_dir / "assets"
        article_dir.mkdir(parents=True, exist_ok=True)

        url_map = download_images(image_urls, assets_dir)
        self.logger.info(f"  Images downloaded: {len(url_map)}")

        # 3. Rewrite image sources to local paths
        final_body = rewrite_image_sources(cleaned_body, url_map)

        # 4. Build and save HTML file
        html_content = build_docmost_html(final_body, metadata)
        html_filename = sanitize_filename(title) + ".html"
        html_path = article_dir / html_filename
        html_path.write_text(html_content, encoding="utf-8")

        # 5. Create ZIP archive for Docmost Generic ZIP Import
        zip_path = self.output_dir / f"{sanitize_filename(title)}.zip"
        create_zip(article_dir, zip_path)
        self.logger.info(f"  ZIP created: {zip_path.name}")

        return {
            "article_id": article_id,
            "title": title,
            "url": metadata["source_url"],
            "status": "ok",
            "zip_path": str(zip_path),
            "images_downloaded": len(url_map),
            "loom_embeds": clean_stats.get("loom_embeds", 0),
            "unsupported_iframes": clean_stats.get("unsupported_iframes", 0),
        }

    # ------------------------------------------------------------------ #
    # Spider close                                                          #
    # ------------------------------------------------------------------ #

    def closed(self, reason):
        ok = [r for r in self.processed_results if r.get("status") == "ok"]
        err = [r for r in self.processed_results if r.get("status") != "ok"]

        self.logger.info("=" * 60)
        self.logger.info("CRAWL COMPLETE")
        self.logger.info("=" * 60)
        self.logger.info(f"Sections discovered : {len(self.discovered_sections)}")
        self.logger.info(f"Articles discovered : {len(self.discovered_articles)}")
        self.logger.info(
            f"POC articles        : {len(ok)} ok / {len(err)} error(s)"
        )
        self.logger.info("")
        for r in ok:
            self.logger.info(f"  [OK]  {r['article_id']}: {r['title']}")
            self.logger.info(
                f"        images={r['images_downloaded']}  "
                f"loom={r['loom_embeds']}  "
                f"zip={Path(r['zip_path']).name}"
            )
        for r in err:
            self.logger.info(
                f"  [ERR] {r['article_id']}: {r.get('error', 'unknown error')}"
            )
        self.logger.info("=" * 60)


# =========================================================================== #
# Runner                                                                        #
# =========================================================================== #


def run_crawler(output_dir: str = "output/scrapy") -> None:
    """Run the Scrapy crawler (blocking)."""
    process = CrawlerProcess(
        settings={"LOG_FORMAT": "%(levelname)s: %(message)s"}
    )
    process.crawl(ContactsPlusSpider, output_dir=output_dir)
    process.start()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Crawl Contacts+ Help Center and produce Docmost ZIP files.\n"
            "Starts from homepage, discovers sections → articles, "
            "processes only the 3 POC article IDs."
        )
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="output/scrapy",
        help="Output directory for migrated articles (default: output/scrapy)",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("Contacts+ Help Center → Docmost migration crawler")
    print("=" * 60)
    print(f"Start URL : {START_URL}")
    print(f"Output dir: {args.output_dir}")
    print(f"POC IDs   : {', '.join(sorted(POC_ARTICLE_IDS))}")
    print("=" * 60)
    print()

    run_crawler(args.output_dir)
