#!/usr/bin/env python3
"""
Automatic KB Discovery Crawler for Contacts+ Help Center.

Crawls from the homepage, discovers categories, sections, and articles
through web scraping (no API usage).

Uses requests + BeautifulSoup for crawling (Scrapy was receiving 403 responses).
"""

import re
import time
from pathlib import Path
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
    build_docmost_html,
    create_zip,
)


class KBDiscoveryCrawler:
    """Crawler to discover all articles in the Contacts+ Help Center."""
    
    def __init__(self, discovery_only: bool = True, test_articles: list[str] | None = None,
                 output_dir: str = "output/scrapy"):
        self.discovery_only = discovery_only
        self.test_articles = set(test_articles or [])
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        }
        
        # Discovery tracking
        self.discovered_categories = {}
        self.discovered_sections = {}
        self.discovered_articles = set()
        self.article_hierarchy = []
        
        # Processing tracking
        self.processed_articles = []
        self.article_metadata = {}
        
        self.base_url = "https://support.contactsplus.com"
    
    def fetch_page(self, url: str) -> str | None:
        """Fetch a page with proper headers."""
        try:
            print(f"Fetching: {url}")
            response = requests.get(url, headers=self.headers, timeout=30)
            
            if response.status_code == 403:
                print(f"ERROR: 403 Forbidden - {url}")
                return None
            
            response.raise_for_status()
            print(f"  Status: {response.status_code}, Size: {len(response.text)} bytes")
            return response.text
            
        except requests.RequestException as e:
            print(f"ERROR: Failed to fetch {url}: {e}")
            return None
    
    def crawl_homepage(self):
        """Crawl the KB homepage and discover categories/sections."""
        url = f"{self.base_url}/hc/en-us"
        html = self.fetch_page(url)
        
        if not html:
            print("ERROR: Could not fetch homepage")
            return
        
        soup = BeautifulSoup(html, 'html.parser')
        
        # Strategy 1: Look for category/section blocks
        # Common patterns: blocks-item-link, section-link, category links
        links = []
        
        # Try finding category/section links
        for selector in [
            'a.blocks-item-link',
            'a.section-link',
            'section.category-list a',
            'a[href*="/categories/"]',
            'a[href*="/sections/"]',
        ]:
            found = soup.select(selector)
            if found:
                links.extend([a.get('href') for a in found if a.get('href')])
        
        # Deduplicate
        links = list(set(links))
        
        print(f"\n{'='*60}")
        print(f"Homepage crawl complete")
        print(f"Found {len(links)} category/section links")
        print(f"{'='*60}\n")
        
        # Process each link
        for link in links:
            full_url = urljoin(self.base_url, link)
            
            if '/categories/' in link:
                match = re.search(r'/categories/(\d+)', link)
                if match:
                    category_id = match.group(1)
                    print(f"\nDiscovered category: {category_id}")
                    time.sleep(2)  # Be polite
                    self.crawl_category(category_id, full_url)
            
            elif '/sections/' in link:
                match = re.search(r'/sections/(\d+)', link)
                if match:
                    section_id = match.group(1)
                    print(f"\nDiscovered section: {section_id}")
                    time.sleep(2)  # Be polite
                    self.crawl_section(section_id, full_url)
    
    def crawl_category(self, category_id: str, url: str):
        """Crawl a category page and discover sections."""
        html = self.fetch_page(url)
        if not html:
            return
        
        soup = BeautifulSoup(html, 'html.parser')
        
        # Extract category name
        category_name = None
        for selector in ['h1', 'h1.page-header', 'header h1']:
            h1 = soup.select_one(selector)
            if h1:
                category_name = h1.get_text(strip=True)
                break
        
        if category_name:
            self.discovered_categories[category_id] = category_name
            print(f"  Category name: {category_name}")
        
        # Find section links
        section_links = []
        for selector in [
            'a.section-link',
            'a[href*="/sections/"]',
            'section a[href*="/sections/"]',
        ]:
            found = soup.select(selector)
            section_links.extend([a.get('href') for a in found if a.get('href')])
        
        section_links = list(set(section_links))
        print(f"  Found {len(section_links)} sections")
        
        for link in section_links:
            match = re.search(r'/sections/(\d+)', link)
            if match:
                section_id = match.group(1)
                full_url = urljoin(self.base_url, link)
                time.sleep(2)  # Be polite
                self.crawl_section(section_id, full_url, category_id, category_name)
    
    def crawl_section(self, section_id: str, url: str, category_id: str | None = None,
                      category_name: str | None = None):
        """Crawl a section page and discover articles."""
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
        
        if section_name:
            self.discovered_sections[section_id] = {
                'name': section_name,
                'category_id': category_id,
                'category_name': category_name,
            }
            print(f"  Section name: {section_name}")
        
        # Find article links
        article_links = []
        for selector in [
            'a.article-list-link',
            'a[href*="/articles/"]',
            'ul.article-list a[href*="/articles/"]',
        ]:
            found = soup.select(selector)
            article_links.extend([a.get('href') for a in found if a.get('href')])
        
        article_links = list(set(article_links))
        print(f"  Found {len(article_links)} articles")
        
        for link in article_links:
            match = re.search(r'/articles/(\d+)', link)
            if match:
                article_id = match.group(1)
                
                # Deduplicate
                if article_id in self.discovered_articles:
                    continue
                
                self.discovered_articles.add(article_id)
                full_url = urljoin(self.base_url, link)
                
                # Store hierarchy
                self.article_hierarchy.append({
                    'article_id': article_id,
                    'article_url': full_url,
                    'section_id': section_id,
                    'section_name': section_name,
                    'category_id': category_id,
                    'category_name': category_name,
                })
                
                print(f"    Article: {article_id}")
                
                # Process if needed
                if self.discovery_only:
                    if article_id in self.test_articles:
                        print(f"      -> Processing test article {article_id}")
                        time.sleep(2)
                        self.process_article(article_id, full_url, section_id, section_name,
                                           category_id, category_name)
                else:
                    # Full migration mode
                    time.sleep(2)
                    self.process_article(article_id, full_url, section_id, section_name,
                                       category_id, category_name)
        
        # Handle pagination
        next_link = None
        for selector in ['a.pagination-next', 'a[rel="next"]', 'a.next']:
            next_a = soup.select_one(selector)
            if next_a:
                next_link = next_a.get('href')
                break
        
        if next_link:
            print(f"  Following pagination...")
            full_url = urljoin(self.base_url, next_link)
            time.sleep(2)
            self.crawl_section(section_id, full_url, category_id, category_name)
    
    def process_article(self, article_id: str, url: str, section_id: str | None,
                       section_name: str | None, category_id: str | None,
                       category_name: str | None):
        """Process an article and create Docmost package."""
        print(f"\n{'='*60}")
        print(f"Processing article {article_id}")
        print(f"URL: {url}")
        print(f"{'='*60}")
        
        html = self.fetch_page(url)
        if not html:
            print(f"ERROR: Could not fetch article {article_id}")
            return
        
        # Use BeautifulSoup for processing
        html_content = self._absolutize_urls(html)
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Extract metadata
        title = self._extract_title(soup)
        article_body_html = self._extract_article_body(soup)
        
        if not article_body_html:
            print(f"ERROR: No article body found for {article_id}")
            return
        
        print(f"Title: {title}")
        print(f"Section: {section_name}, Category: {category_name}")
        
        # Extract images, iframes, links BEFORE cleaning
        image_urls_raw = self._extract_image_urls(soup)
        iframe_urls_raw = self._extract_iframe_urls(soup)
        internal_links = self._extract_internal_links(soup)
        
        print(f"Images (before cleaning): {len(image_urls_raw)}")
        print(f"Iframes (before cleaning): {len(iframe_urls_raw)}")
        print(f"Internal links: {len(internal_links)}")
        
        # Clean HTML using existing transformation logic
        print("Cleaning HTML...")
        cleaned_body, clean_stats = clean_html(article_body_html)
        
        print(f"Loom embeds: {clean_stats.get('loom_embeds', 0)}")
        print(f"Unsupported iframes: {clean_stats.get('unsupported_iframes', 0)}")
        
        # Extract and download images
        image_urls = extract_remote_images(cleaned_body)
        print(f"Images to download (after cleaning): {len(image_urls)}")
        
        article_dir = self.output_dir / sanitize_filename(title)
        assets_dir = article_dir / "assets"
        article_dir.mkdir(parents=True, exist_ok=True)
        
        print("Downloading images...")
        url_map = download_images(image_urls, assets_dir)
        print(f"Images downloaded: {len(url_map)}")
        
        final_body = rewrite_image_sources(cleaned_body, url_map)
        
        # Build metadata
        metadata = {
            "article_id": article_id,
            "title": title,
            "source_url": url,
            "section_id": section_id,
            "section_name": section_name,
            "category_id": category_id,
            "category_name": category_name,
            "updated_at": None,
        }
        
        # Build Docmost-compatible HTML
        html_content = build_docmost_html(final_body, metadata)
        
        # Save HTML file
        html_filename = f"{title}.html"
        html_path = article_dir / html_filename
        html_path.write_text(html_content, encoding="utf-8")
        print(f"HTML saved: {html_path}")
        
        # Create ZIP archive
        zip_path = self.output_dir / f"{sanitize_filename(title)}.zip"
        create_zip(article_dir, zip_path)
        print(f"ZIP created: {zip_path}")
        
        self.processed_articles.append({
            "article_id": article_id,
            "title": title,
            "url": url,
            "image_count": len(image_urls),
            "iframe_count": len(iframe_urls_raw),
            "loom_embeds": clean_stats.get('loom_embeds', 0),
            "downloaded_images": len(url_map),
        })
        
        self.article_metadata[article_id] = {
            **metadata,
            "clean_stats": clean_stats,
            "downloaded_images": len(url_map),
            "image_count": len(image_urls),
            "iframe_count": len(iframe_urls_raw),
            "internal_link_count": len(internal_links),
        }
        
        print(f"{'='*60}\n")
    
    def _absolutize_urls(self, html: str) -> str:
        """Convert relative URLs to absolute URLs."""
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
        title_selectors = [
            ('h1', 'article-title'),
            ('h1', None),
        ]
        
        for tag_name, class_name in title_selectors:
            if class_name:
                title_tag = soup.find(tag_name, class_=class_name)
            else:
                title_tag = soup.find(tag_name)
            
            if title_tag:
                title = title_tag.get_text(strip=True)
                if title and '|' in title:
                    title = title.split('|')[0].strip()
                if title:
                    return title
        
        # Fallback
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
        selectors = [
            ('div', 'article-body'),
            ('article', 'article'),
            ('div', 'article-content'),
        ]
        
        for tag_name, class_name in selectors:
            if class_name:
                article_body = soup.find(tag_name, class_=class_name)
            else:
                article_body = soup.find(tag_name)
            
            if article_body:
                return str(article_body)
        
        return ""
    
    def _extract_image_urls(self, soup: BeautifulSoup) -> list[str]:
        """Extract image URLs from article body."""
        article_body = soup.find('div', class_='article-body')
        if not article_body:
            article_body = soup.find('article')
        
        if not article_body:
            return []
        
        image_urls = []
        for img in article_body.find_all('img'):
            src = img.get('src', '').strip()
            if src and src.startswith(('http://', 'https://')):
                image_urls.append(src)
        
        return image_urls
    
    def _extract_iframe_urls(self, soup: BeautifulSoup) -> list[str]:
        """Extract iframe URLs from article body."""
        article_body = soup.find('div', class_='article-body')
        if not article_body:
            article_body = soup.find('article')
        
        if not article_body:
            return []
        
        iframe_urls = []
        for iframe in article_body.find_all('iframe'):
            src = iframe.get('src', '').strip()
            if src:
                iframe_urls.append(src)
        
        return iframe_urls
    
    def _extract_internal_links(self, soup: BeautifulSoup) -> list[str]:
        """Extract internal article links."""
        article_body = soup.find('div', class_='article-body')
        if not article_body:
            article_body = soup.find('article')
        
        if not article_body:
            return []
        
        internal_links = []
        for link in article_body.find_all('a', href=True):
            href = link['href']
            if '/articles/' in href:
                internal_links.append(href)
        
        return internal_links
    
    def print_summary(self):
        """Print crawler summary."""
        print(f"\n\n{'='*60}")
        print("DISCOVERY RESULTS")
        print(f"{'='*60}")
        print(f"Homepage: {self.base_url}/hc/en-us")
        print(f"Categories discovered: {len(self.discovered_categories)}")
        print(f"Sections discovered: {len(self.discovered_sections)}")
        print(f"Unique articles discovered: {len(self.discovered_articles)}")
        print(f"Articles processed: {len(self.processed_articles)}")
        
        if self.discovered_categories:
            print(f"\n{'='*60}")
            print("CATEGORIES:")
            print(f"{'='*60}")
            for cat_id, cat_name in self.discovered_categories.items():
                print(f"  - {cat_name} (ID: {cat_id})")
        
        if self.discovered_sections:
            print(f"\n{'='*60}")
            print("SECTIONS:")
            print(f"{'='*60}")
            for sec_id, sec_info in self.discovered_sections.items():
                cat_name = sec_info.get('category_name', 'Unknown')
                print(f"  - {sec_info['name']} (ID: {sec_id}, Category: {cat_name})")
        
        if self.processed_articles:
            print(f"\n{'='*60}")
            print("PROCESSED ARTICLES:")
            print(f"{'='*60}")
            for article in self.processed_articles:
                print(f"\n  {article['title']} (ID: {article['article_id']})")
                print(f"    URL: {article['url']}")
                print(f"    Images: {article['image_count']}, Loom embeds: {article['loom_embeds']}")
                print(f"    Downloaded images: {article['downloaded_images']}")
        
        # Hierarchy reconstruction check
        if self.article_hierarchy:
            print(f"\n{'='*60}")
            print("HIERARCHY RECONSTRUCTION:")
            print(f"{'='*60}")
            print(f"Total article entries: {len(self.article_hierarchy)}")
            
            # Group by category
            by_category = {}
            for entry in self.article_hierarchy:
                cat_name = entry.get('category_name', 'Uncategorized')
                if cat_name not in by_category:
                    by_category[cat_name] = {}
                
                sec_name = entry.get('section_name', 'Unnamed Section')
                if sec_name not in by_category[cat_name]:
                    by_category[cat_name][sec_name] = []
                
                by_category[cat_name][sec_name].append(entry['article_id'])
            
            for cat_name, sections in by_category.items():
                print(f"\n  Category: {cat_name}")
                for sec_name, articles in sections.items():
                    print(f"    Section: {sec_name}")
                    print(f"      Articles: {len(articles)}")
        
        print(f"\n{'='*60}")
        print("PAGINATION STATUS:")
        print(f"{'='*60}")
        print("Pagination handling: Implemented (will follow next links if present)")
        
        print(f"\n{'='*60}\n")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Automatic KB Discovery Crawler for Contacts+ Help Center"
    )
    parser.add_argument(
        "--discovery-only",
        action="store_true",
        default=True,
        help="Run discovery only (don't process all articles)",
    )
    parser.add_argument(
        "--test-articles",
        type=str,
        nargs="+",
        default=["4407286476827", "4406997562651", "4410672626203"],
        help="Test article IDs to process in discovery mode",
    )
    parser.add_argument(
        "--full-migration",
        action="store_true",
        help="Process all discovered articles (overrides discovery-only)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="output/scrapy",
        help="Output directory for processed articles",
    )
    
    args = parser.parse_args()
    
    discovery_only = not args.full_migration
    
    print(f"{'='*60}")
    print("KB DISCOVERY CRAWLER")
    print(f"{'='*60}")
    print(f"Mode: {'Discovery Only' if discovery_only else 'Full Migration'}")
    print(f"Test articles: {args.test_articles if discovery_only else 'N/A (processing all)'}")
    print(f"Output directory: {args.output_dir}")
    print(f"{'='*60}\n")
    
    crawler = KBDiscoveryCrawler(
        discovery_only=discovery_only,
        test_articles=args.test_articles,
        output_dir=args.output_dir
    )
    
    crawler.crawl_homepage()
    crawler.print_summary()


if __name__ == "__main__":
    main()
