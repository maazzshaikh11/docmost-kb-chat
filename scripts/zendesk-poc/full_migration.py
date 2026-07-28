#!/usr/bin/env python3
"""
Full Contacts+ Knowledge Base Migration.

Crawls the entire KB from the homepage, discovers all sections and articles,
and processes them with fault tolerance and validation.

Uses web scraping only (no API calls).
"""

import re
import time
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# Import transformation functions from existing code
from migrate_article import (
    clean_html,
    download_images,
    extract_remote_images,
    rewrite_image_sources,
    sanitize_filename,
)


class FullMigrationCrawler:
    """Full KB migration crawler with fault tolerance."""
    
    def __init__(self, output_dir: str = "output/full_migration"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        }
        
        self.base_url = "https://support.contactsplus.com"
        
        # Discovery tracking
        self.discovered_sections = {}
        self.discovered_articles = set()
        self.article_hierarchy = []
        
        # Processing tracking
        self.successful_articles = []
        self.failed_articles = []
        self.article_metadata = {}
        
        # Asset tracking
        self.total_assets_downloaded = 0
        self.failed_assets = []
        self.asset_download_map = {}
        
        # Link tracking
        self.internal_links_found = 0
        self.article_id_to_path = {}  # article_id -> local path
        
        # Stats
        self.stats = {
            'total_embeds': 0,
            'loom_embeds': 0,
            'unsupported_iframes': 0,
            'failed_requests': 0,
            'warnings': [],
        }
        
        # Rate limiting
        self.request_delay = 2.0
        self.max_retries = 3
        self.request_timeout = 30
    
    def fetch_page(self, url: str, retry_count: int = 0) -> str | None:
        """Fetch a page with retries and error handling."""
        try:
            print(f"Fetching: {url}")
            response = requests.get(
                url,
                headers=self.headers,
                timeout=self.request_timeout,
                allow_redirects=True
            )
            
            if response.status_code == 403:
                print(f"  ERROR: 403 Forbidden")
                self.stats['failed_requests'] += 1
                return None
            
            response.raise_for_status()
            print(f"  OK ({len(response.text)} bytes)")
            return response.text
            
        except requests.Timeout:
            if retry_count < self.max_retries:
                print(f"  Timeout, retrying ({retry_count + 1}/{self.max_retries})...")
                time.sleep(self.request_delay * 2)
                return self.fetch_page(url, retry_count + 1)
            print(f"  ERROR: Timeout after {self.max_retries} retries")
            self.stats['failed_requests'] += 1
            return None
            
        except requests.RequestException as e:
            if retry_count < self.max_retries:
                print(f"  Error: {e}, retrying ({retry_count + 1}/{self.max_retries})...")
                time.sleep(self.request_delay * 2)
                return self.fetch_page(url, retry_count + 1)
            print(f"  ERROR: {e}")
            self.stats['failed_requests'] += 1
            return None
    
    def crawl_homepage(self):
        """Crawl the KB homepage and discover sections."""
        print(f"\n{'='*60}")
        print("STARTING FULL KB MIGRATION")
        print(f"{'='*60}\n")
        
        url = f"{self.base_url}/hc/en-us"
        html = self.fetch_page(url)
        
        if not html:
            print("FATAL: Could not fetch homepage")
            return
        
        soup = BeautifulSoup(html, 'html.parser')
        
        # Find all section links
        links = []
        for selector in [
            'a.blocks-item-link',
            'a.section-link',
            'section.category-list a',
            'a[href*="/sections/"]',
        ]:
            found = soup.select(selector)
            if found:
                links.extend([a.get('href') for a in found if a.get('href')])
        
        links = list(set(links))
        section_links = [l for l in links if '/sections/' in l]
        
        print(f"\n{'='*60}")
        print(f"Homepage: {len(section_links)} sections discovered")
        print(f"{'='*60}\n")
        
        # Crawl each section
        for i, link in enumerate(section_links, 1):
            match = re.search(r'/sections/(\d+)', link)
            if match:
                section_id = match.group(1)
                full_url = urljoin(self.base_url, link)
                
                print(f"\n[{i}/{len(section_links)}] Section {section_id}")
                time.sleep(self.request_delay)
                
                try:
                    self.crawl_section(section_id, full_url)
                except Exception as e:
                    print(f"  ERROR crawling section: {e}")
                    self.stats['warnings'].append(f"Section {section_id} crawl failed: {e}")
    
    def crawl_section(self, section_id: str, url: str):
        """Crawl a section and discover articles."""
        html = self.fetch_page(url)
        if not html:
            return
        
        soup = BeautifulSoup(html, 'html.parser')
        
        # Extract section name
        section_name = None
        for selector in ['h1', 'h1.page-header', 'header h1']:
            h1 = soup.select_one(selector)
            if h1:
                section_name = h1.get_text(strip=True)
                break
        
        if not section_name:
            section_name = f"Section {section_id}"
        
        self.discovered_sections[section_id] = {'name': section_name}
        print(f"  Section: {section_name}")
        
        # Find article links - IMPORTANT: preserve full URL with slug
        article_links = []
        for selector in [
            'a.article-list-link',
            'a[href*="/articles/"]',
            'ul.article-list a[href*="/articles/"]',
        ]:
            found = soup.select(selector)
            article_links.extend([a.get('href') for a in found if a.get('href')])
        
        article_links = list(set(article_links))
        print(f"  Articles: {len(article_links)}")
        
        for link in article_links:
            match = re.search(r'/articles/(\d+)', link)
            if match:
                article_id = match.group(1)
                
                if article_id in self.discovered_articles:
                    continue
                
                self.discovered_articles.add(article_id)
                
                # IMPORTANT: Use the full discovered URL with slug
                full_url = urljoin(self.base_url, link)
                
                self.article_hierarchy.append({
                    'article_id': article_id,
                    'article_url': full_url,  # This now includes the slug
                    'section_id': section_id,
                    'section_name': section_name,
                })
                
                print(f"    [{article_id}] Queued")
        
        # Handle pagination
        next_link = None
        for selector in ['a.pagination-next', 'a[rel="next"]', 'a.next']:
            next_a = soup.select_one(selector)
            if next_a:
                next_link = next_a.get('href')
                break
        
        if next_link:
            print(f"  Pagination: following next page")
            full_url = urljoin(self.base_url, next_link)
            time.sleep(self.request_delay)
            self.crawl_section(section_id, full_url)
    
    def process_all_articles(self):
        """Process all discovered articles with fault tolerance."""
        print(f"\n{'='*60}")
        print(f"PROCESSING {len(self.article_hierarchy)} ARTICLES")
        print(f"{'='*60}\n")
        
        for i, article_info in enumerate(self.article_hierarchy, 1):
            article_id = article_info['article_id']
            article_url = article_info['article_url']
            section_id = article_info['section_id']
            section_name = article_info['section_name']
            
            print(f"\n[{i}/{len(self.article_hierarchy)}] Article {article_id}")
            
            time.sleep(self.request_delay)
            
            try:
                self.process_article(
                    article_id,
                    article_url,
                    section_id,
                    section_name
                )
            except Exception as e:
                print(f"  ERROR: {e}")
                self.failed_articles.append({
                    'article_id': article_id,
                    'url': article_url,
                    'error': str(e),
                })
                self.stats['warnings'].append(f"Article {article_id} failed: {e}")
    
    def process_article(self, article_id: str, url: str, section_id: str, section_name: str):
        """Process a single article."""
        html = self.fetch_page(url)
        if not html:
            raise ValueError(f"Could not fetch article {article_id}")
        
        html_content = self._absolutize_urls(html)
        soup = BeautifulSoup(html_content, 'html.parser')
        
        title = self._extract_title(soup)
        article_body_html = self._extract_article_body(soup)
        
        if not article_body_html:
            raise ValueError(f"No article body found")
        
        print(f"  Title: {title}")
        
        # Extract metadata before cleaning
        image_urls_raw = self._extract_image_urls(soup)
        iframe_urls_raw = self._extract_iframe_urls(soup)
        internal_links = self._extract_internal_links(soup)
        
        self.internal_links_found += len(internal_links)
        
        print(f"  Images: {len(image_urls_raw)}, Iframes: {len(iframe_urls_raw)}, Internal links: {len(internal_links)}")
        
        # Clean HTML
        cleaned_body, clean_stats = clean_html(article_body_html)
        
        self.stats['loom_embeds'] += clean_stats.get('loom_embeds', 0)
        self.stats['unsupported_iframes'] += clean_stats.get('unsupported_iframes', 0)
        
        # Download images
        image_urls = extract_remote_images(cleaned_body)
        
        # Create section directory structure
        section_dir = self.output_dir / sanitize_filename(section_name)
        article_dir = section_dir / sanitize_filename(title)
        assets_dir = article_dir / "assets"
        article_dir.mkdir(parents=True, exist_ok=True)
        
        # Download images with fault tolerance
        url_map = {}
        downloaded_count = 0
        for img_url in image_urls:
            try:
                downloaded = self._download_single_image(img_url, assets_dir)
                if downloaded:
                    url_map[img_url] = downloaded
                    downloaded_count += 1
            except Exception as e:
                print(f"    Warning: Failed to download image: {e}")
                self.failed_assets.append({
                    'url': img_url,
                    'article_id': article_id,
                    'error': str(e),
                })
        
        # Update global count
        self.total_assets_downloaded += downloaded_count
        
        final_body = rewrite_image_sources(cleaned_body, url_map)
        
        # Build metadata
        metadata = {
            "article_id": article_id,
            "title": title,
            "source_url": url,
            "section_id": section_id,
            "section_name": section_name,
            "updated_at": None,
        }
        
        # Build HTML
        html_content = self._build_docmost_html(final_body, metadata)
        
        # Save HTML (sanitize filename to handle slashes)
        html_filename = f"{sanitize_filename(title)}.html"
        html_path = article_dir / html_filename
        html_path.write_text(html_content, encoding="utf-8")
        
        # Track article path for internal link mapping
        relative_path = f"{sanitize_filename(section_name)}/{sanitize_filename(title)}/{html_filename}"
        self.article_id_to_path[article_id] = relative_path
        
        print(f"  Saved: {relative_path}")
        
        self.successful_articles.append({
            "article_id": article_id,
            "title": title,
            "section": section_name,
            "url": url,
            "images": len(url_map),
            "loom_embeds": clean_stats.get('loom_embeds', 0),
        })
        
        self.article_metadata[article_id] = {
            **metadata,
            "clean_stats": clean_stats,
            "image_count": len(url_map),
        }
    
    def _download_single_image(self, url: str, assets_dir: Path) -> str | None:
        """Download a single image with retries."""
        assets_dir.mkdir(parents=True, exist_ok=True)
        
        # Check if already downloaded
        if url in self.asset_download_map:
            return self.asset_download_map[url]
        
        for retry in range(self.max_retries):
            try:
                response = requests.get(url, timeout=60)
                response.raise_for_status()
                
                # Determine filename
                filename = self._filename_from_url(url)
                
                # Infer extension from Content-Type if needed
                if '.' not in filename or filename.endswith('.'):
                    content_type = response.headers.get('Content-Type', '').split(';')[0].strip().lower()
                    mime_to_ext = {
                        'image/png': '.png',
                        'image/jpeg': '.jpg',
                        'image/jpg': '.jpg',
                        'image/gif': '.gif',
                        'image/webp': '.webp',
                        'image/svg+xml': '.svg',
                    }
                    ext = mime_to_ext.get(content_type, '.png')
                    
                    path_parts = urlparse(url).path.split('/')
                    numeric_id = next((part for part in reversed(path_parts) if part.isdigit()), None)
                    if numeric_id:
                        filename = f"{numeric_id}{ext}"
                    else:
                        filename = f"image-{abs(hash(url)) % 10000}{ext}"
                
                destination = assets_dir / filename
                
                # Handle duplicates
                counter = 1
                while destination.exists():
                    stem = destination.stem
                    suffix = destination.suffix
                    destination = assets_dir / f"{stem}-{counter}{suffix}"
                    counter += 1
                
                destination.write_bytes(response.content)
                
                local_path = f"assets/{destination.name}"
                self.asset_download_map[url] = local_path
                return local_path
                
            except Exception as e:
                if retry < self.max_retries - 1:
                    time.sleep(1)
                    continue
                raise e
        
        return None
    
    def _filename_from_url(self, url: str) -> str:
        """Extract filename from URL."""
        from urllib.parse import unquote
        path = unquote(urlparse(url).path)
        basename = Path(path).name
        if basename:
            return sanitize_filename(basename)
        return "image.png"
    
    def _absolutize_urls(self, html: str) -> str:
        """Convert relative URLs to absolute."""
        soup = BeautifulSoup(html, "html.parser")
        
        for img in soup.find_all("img", src=True):
            src = img["src"]
            if src.startswith("/"):
                img["src"] = self.base_url + src
            elif not src.startswith(("http://", "https://")):
                img["src"] = urljoin(self.base_url + "/hc/en-us/", src)
        
        return str(soup)
    
    def _extract_title(self, soup: BeautifulSoup) -> str:
        """Extract article title."""
        for selector in [('h1', 'article-title'), ('h1', None)]:
            tag_name, class_name = selector
            title_tag = soup.find(tag_name, class_=class_name) if class_name else soup.find(tag_name)
            if title_tag:
                title = title_tag.get_text(strip=True)
                if '|' in title:
                    title = title.split('|')[0].strip()
                if title:
                    return title
        
        title_tag = soup.find('title')
        if title_tag:
            title = title_tag.get_text(strip=True)
            if '|' in title:
                title = title.split('|')[0].strip()
            if title:
                return title
        
        return "Untitled Article"
    
    def _extract_article_body(self, soup: BeautifulSoup) -> str:
        """Extract article body HTML."""
        for tag_name, class_name in [('div', 'article-body'), ('article', 'article')]:
            article_body = soup.find(tag_name, class_=class_name) if class_name else soup.find(tag_name)
            if article_body:
                return str(article_body)
        return ""
    
    def _extract_image_urls(self, soup: BeautifulSoup) -> list[str]:
        """Extract image URLs."""
        article_body = soup.find('div', class_='article-body') or soup.find('article')
        if not article_body:
            return []
        
        return [img.get('src', '').strip() for img in article_body.find_all('img')
                if img.get('src', '').strip().startswith(('http://', 'https://'))]
    
    def _extract_iframe_urls(self, soup: BeautifulSoup) -> list[str]:
        """Extract iframe URLs."""
        article_body = soup.find('div', class_='article-body') or soup.find('article')
        if not article_body:
            return []
        
        return [iframe.get('src', '').strip() for iframe in article_body.find_all('iframe')
                if iframe.get('src', '').strip()]
    
    def _extract_internal_links(self, soup: BeautifulSoup) -> list[str]:
        """Extract internal KB article links."""
        article_body = soup.find('div', class_='article-body') or soup.find('article')
        if not article_body:
            return []
        
        internal_links = []
        for link in article_body.find_all('a', href=True):
            href = link['href']
            if '/articles/' in href:
                internal_links.append(href)
        return internal_links
    
    def _build_docmost_html(self, body: str, metadata: dict) -> str:
        """Build Docmost-compatible HTML."""
        title = metadata["title"]
        comment_lines = [
            f"Source URL: {metadata['source_url']}",
            f"Section ID: {metadata['section_id']}",
            f"Section: {metadata['section_name']}",
            f"Article ID: {metadata['article_id']}",
        ]
        comment = "\n".join(f"  {line}" for line in comment_lines)
        return (
            "<!DOCTYPE html>\n"
            f"<html>\n<head>\n  <meta charset=\"utf-8\">\n"
            f"  <title>{title}</title>\n  <!--\n{comment}\n  -->\n"
            f"</head>\n<body>\n{body}\n</body>\n</html>\n"
        )
    
    def create_final_zip(self) -> Path:
        """Create final ZIP archive with all sections and articles."""
        zip_path = self.output_dir.parent / "Contacts_Plus_KB_Full_Migration.zip"
        
        print(f"\n{'='*60}")
        print("CREATING FINAL ZIP ARCHIVE")
        print(f"{'='*60}\n")
        
        with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(self.output_dir.rglob("*")):
                if path.is_file():
                    rel_path = path.relative_to(self.output_dir)
                    archive.write(path, arcname=rel_path.as_posix())
                    print(f"  Added: {rel_path}")
        
        print(f"\nZIP created: {zip_path}")
        print(f"ZIP size: {zip_path.stat().st_size / (1024*1024):.2f} MB")
        
        return zip_path
    
    def validate_output(self, zip_path: Path):
        """Validate the migration output."""
        print(f"\n{'='*60}")
        print("VALIDATION RESULTS")
        print(f"{'='*60}\n")
        
        # Count generated files
        html_files = list(self.output_dir.rglob("*.html"))
        asset_files = list(self.output_dir.rglob("assets/*"))
        
        print(f"Discovered articles: {len(self.discovered_articles)}")
        print(f"Generated HTML files: {len(html_files)}")
        print(f"Successful migrations: {len(self.successful_articles)}")
        print(f"Failed migrations: {len(self.failed_articles)}")
        
        # Check for missing articles
        generated_ids = {a['article_id'] for a in self.successful_articles}
        missing_ids = self.discovered_articles - generated_ids
        
        if missing_ids:
            print(f"\nMissing articles: {len(missing_ids)}")
            for aid in list(missing_ids)[:10]:
                print(f"  - {aid}")
            if len(missing_ids) > 10:
                print(f"  ... and {len(missing_ids) - 10} more")
        else:
            print(f"\nMissing articles: 0 ✓")
        
        # Check for duplicates
        article_counts = defaultdict(int)
        for a in self.successful_articles:
            article_counts[a['article_id']] += 1
        
        duplicates = {aid: count for aid, count in article_counts.items() if count > 1}
        if duplicates:
            print(f"\nDuplicate articles: {len(duplicates)}")
            for aid, count in list(duplicates.items())[:5]:
                print(f"  - {aid}: {count} times")
        else:
            print(f"Duplicate articles: 0 ✓")
        
        print(f"\nTotal assets downloaded: {self.total_assets_downloaded}")
        print(f"Failed assets: {len(self.failed_assets)}")
        
        # Check for broken local asset references
        broken_refs = []
        for html_file in html_files:
            content = html_file.read_text(encoding='utf-8')
            soup = BeautifulSoup(content, 'html.parser')
            for img in soup.find_all('img', src=True):
                src = img['src']
                if src.startswith('assets/'):
                    asset_path = html_file.parent / src
                    if not asset_path.exists():
                        broken_refs.append((html_file.name, src))
        
        if broken_refs:
            print(f"\nBroken local asset references: {len(broken_refs)}")
            for fname, src in broken_refs[:5]:
                print(f"  - {fname}: {src}")
        else:
            print(f"Broken local asset references: 0 ✓")
        
        # Check for remaining remote image references
        remote_refs = []
        for html_file in html_files:
            content = html_file.read_text(encoding='utf-8')
            soup = BeautifulSoup(content, 'html.parser')
            for img in soup.find_all('img', src=True):
                src = img['src']
                if src.startswith(('http://', 'https://')):
                    remote_refs.append((html_file.name, src))
        
        print(f"Remaining remote image references: {len(remote_refs)}")
        if remote_refs and len(remote_refs) <= 5:
            for fname, src in remote_refs:
                print(f"  - {fname}: {src}")
        
        print(f"\nInternal KB links found: {self.internal_links_found}")
        print(f"(Note: Internal links preserved as-is, pointing to source KB)")
        
        print(f"\nFailed requests: {self.stats['failed_requests']}")
        print(f"Loom embeds converted: {self.stats['loom_embeds']}")
        print(f"Unsupported iframes: {self.stats['unsupported_iframes']}")
        
        # ZIP integrity check
        try:
            with zipfile.ZipFile(zip_path, 'r') as archive:
                bad_files = archive.testzip()
                if bad_files:
                    print(f"\nZIP integrity: FAILED")
                    print(f"  Corrupted file: {bad_files}")
                else:
                    print(f"\nZIP integrity: OK ✓")
                    print(f"ZIP contains {len(archive.namelist())} files")
        except Exception as e:
            print(f"\nZIP integrity: ERROR - {e}")
        
        # Sections
        print(f"\nSections discovered: {len(self.discovered_sections)}")
        for sec_id, sec_info in self.discovered_sections.items():
            articles_in_section = len([a for a in self.successful_articles if a.get('section') == sec_info['name']])
            print(f"  - {sec_info['name']}: {articles_in_section} articles")
    
    def print_summary(self, zip_path: Path):
        """Print final summary."""
        print(f"\n{'='*60}")
        print("MIGRATION COMPLETE")
        print(f"{'='*60}\n")
        
        print(f"Sections discovered: {len(self.discovered_sections)}")
        print(f"Unique articles discovered: {len(self.discovered_articles)}")
        print(f"Articles successfully migrated: {len(self.successful_articles)}")
        print(f"Articles failed/skipped: {len(self.failed_articles)}")
        
        if self.failed_articles:
            print(f"\nFailed articles:")
            for article in self.failed_articles[:10]:
                print(f"  - {article['article_id']}: {article['error']}")
            if len(self.failed_articles) > 10:
                print(f"  ... and {len(self.failed_articles) - 10} more")
        
        print(f"\nTotal assets downloaded: {self.total_assets_downloaded}")
        print(f"Failed assets: {len(self.failed_assets)}")
        
        if self.failed_assets:
            unique_failed = len(set(a['article_id'] for a in self.failed_assets))
            print(f"  Affected articles: {unique_failed}")
        
        print(f"\nEmbed results:")
        print(f"  Loom embeds converted: {self.stats['loom_embeds']}")
        print(f"  Unsupported iframes: {self.stats['unsupported_iframes']}")
        
        print(f"\nInternal-link handling:")
        print(f"  Internal KB links found: {self.internal_links_found}")
        print(f"  Status: Preserved as-is (point to source KB)")
        
        print(f"\nFinal Docmost import ZIP: {zip_path}")
        print(f"ZIP size: {zip_path.stat().st_size / (1024*1024):.2f} MB")
        
        if self.stats['warnings']:
            print(f"\nWarnings: {len(self.stats['warnings'])}")
            for warning in self.stats['warnings'][:10]:
                print(f"  - {warning}")
        
        print(f"\n{'='*60}\n")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Full Contacts+ KB Migration"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="output/full_migration",
        help="Output directory",
    )
    
    args = parser.parse_args()
    
    crawler = FullMigrationCrawler(output_dir=args.output_dir)
    
    # Step 1: Discover all sections and articles
    crawler.crawl_homepage()
    
    # Step 2: Process all articles
    crawler.process_all_articles()
    
    # Step 3: Create final ZIP
    zip_path = crawler.create_final_zip()
    
    # Step 4: Validate output
    crawler.validate_output(zip_path)
    
    # Step 5: Print summary
    crawler.print_summary(zip_path)


if __name__ == "__main__":
    main()
