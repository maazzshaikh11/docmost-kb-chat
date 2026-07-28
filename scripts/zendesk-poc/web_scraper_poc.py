#!/usr/bin/env python3
"""
Web scraper POC for Contacts+ Help Center using requests + BeautifulSoup.

Fetches article HTML pages directly and extracts content.
Uses existing transformation logic from migrate_article.py.
"""

import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

# Import transformation functions from existing migration script
from migrate_article import (
    clean_html,
    download_images,
    extract_remote_images,
    rewrite_image_sources,
    sanitize_filename,
    build_docmost_html,
    create_zip,
)


class ContactsPlusWebScraper:
    """Web scraper for Contacts+ Help Center using requests."""
    
    def __init__(self, output_dir: str = "output/scrapy"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        }
        
        self.processed_articles = []
        self.article_metadata = {}
    
    def fetch_article_page(self, article_id: str) -> str | None:
        """Fetch article HTML page."""
        url = f"https://support.contactsplus.com/hc/en-us/articles/{article_id}"
        
        try:
            print(f"\n{'='*60}")
            print(f"Fetching article {article_id}...")
            print(f"URL: {url}")
            
            response = requests.get(url, headers=self.headers, allow_redirects=True, timeout=30)
            
            print(f"Status code: {response.status_code}")
            print(f"Final URL: {response.url}")
            
            if response.status_code == 403:
                print(f"ERROR: 403 Forbidden - Site is blocking automated requests")
                return None
            
            response.raise_for_status()
            
            print(f"Content length: {len(response.text)} bytes")
            return response.text
            
        except requests.RequestException as e:
            print(f"ERROR: Failed to fetch article {article_id}: {e}")
            return None
    
    def extract_title(self, soup: BeautifulSoup) -> str:
        """Extract article title from the page."""
        # Try multiple selectors
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
                    # Remove "| Contacts+ Help Center" suffix
                    title = title.split('|')[0].strip()
                if title:
                    return title
        
        # Fallback to page title
        title_tag = soup.find('title')
        if title_tag:
            title = title_tag.get_text(strip=True)
            if '|' in title:
                title = title.split('|')[0].strip()
            if title:
                return title
        
        return "Untitled Article"
    
    def extract_section_info(self, soup: BeautifulSoup) -> dict:
        """Extract section/category information from breadcrumbs."""
        info = {
            "section_id": None,
            "section_name": None,
            "category_name": None,
        }
        
        # Try to extract from breadcrumbs
        breadcrumbs = soup.find('nav', {'aria-label': 'Breadcrumb'})
        if not breadcrumbs:
            breadcrumbs = soup.find('ol', {'class': 'breadcrumbs'})
        
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            if len(links) >= 2:
                # Usually: Home > Category > Section > Article
                info["category_name"] = links[1].get_text(strip=True) if len(links) > 1 else None
                info["section_name"] = links[-1].get_text(strip=True) if links else None
                
                # Try to extract section ID from last breadcrumb link
                section_link = links[-1].get('href', '')
                section_match = re.search(r'/sections/(\d+)', section_link)
                if section_match:
                    info["section_id"] = section_match.group(1)
        
        return info
    
    def extract_article_body(self, soup: BeautifulSoup) -> str:
        """Extract the main article body HTML."""
        # Try multiple selectors for article content
        selectors = [
            ('div', 'article-body'),
            ('article', 'article'),
            ('div', 'article-content'),
            ('section', 'article-info'),
        ]
        
        for tag_name, class_name in selectors:
            if class_name:
                article_body = soup.find(tag_name, class_=class_name)
            else:
                article_body = soup.find(tag_name)
            
            if article_body:
                print(f"Found article body using selector: {tag_name}.{class_name if class_name else '(no class)'}")
                return str(article_body)
        
        print("WARNING: Could not find article body with standard selectors")
        return ""
    
    def extract_image_urls(self, soup: BeautifulSoup) -> list[str]:
        """Extract all image URLs from article content."""
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
    
    def extract_iframe_urls(self, soup: BeautifulSoup) -> list[str]:
        """Extract all iframe URLs (embeds) from article content."""
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
    
    def extract_internal_links(self, soup: BeautifulSoup) -> list[str]:
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

    def _absolutize_urls(self, html: str) -> str:
        """Rewrite relative img src and a href URLs to absolute URLs."""
        base_url = "https://support.contactsplus.com"
        from urllib.parse import urljoin
        soup = BeautifulSoup(html, "html.parser")
        for img in soup.find_all("img", src=True):
            src = img["src"]
            if src.startswith("/"):
                img["src"] = base_url + src
            elif not src.startswith(("http://", "https://")):
                img["src"] = urljoin(base_url + "/hc/en-us/", src)
        return str(soup)
    
    def process_article(self, article_id: str, html_content: str):
        """Process article using BeautifulSoup and existing transformation logic."""
        html_content = self._absolutize_urls(html_content)
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Extract metadata from page
        title = self.extract_title(soup)
        section_info = self.extract_section_info(soup)
        article_body_html = self.extract_article_body(soup)
        
        if not article_body_html:
            print(f"ERROR: No article body found for {article_id}")
            return
        
        print(f"\nArticle: {title}")
        print(f"Article ID: {article_id}")
        print(f"Section: {section_info.get('section_name', 'Unknown')}")
        print(f"Category: {section_info.get('category_name', 'Unknown')}")
        
        # Extract images, links, and embeds BEFORE cleaning
        image_urls_raw = self.extract_image_urls(soup)
        iframe_urls_raw = self.extract_iframe_urls(soup)
        internal_links = self.extract_internal_links(soup)
        
        print(f"Images found (before cleaning): {len(image_urls_raw)}")
        print(f"Iframes found (before cleaning): {len(iframe_urls_raw)}")
        print(f"Internal links: {len(internal_links)}")
        
        # Clean HTML using existing transformation logic
        print("\nCleaning HTML...")
        cleaned_body, clean_stats = clean_html(article_body_html)
        
        print(f"Loom embeds converted: {clean_stats.get('loom_embeds', 0)}")
        print(f"Unsupported iframes: {clean_stats.get('unsupported_iframes', 0)}")
        
        # Extract and download images from cleaned HTML
        image_urls = extract_remote_images(cleaned_body)
        print(f"Images to download (after cleaning): {len(image_urls)}")
        
        article_dir = self.output_dir / sanitize_filename(title)
        assets_dir = article_dir / "assets"
        article_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"\nDownloading images...")
        url_map = download_images(image_urls, assets_dir)
        print(f"Images downloaded: {len(url_map)}")
        
        final_body = rewrite_image_sources(cleaned_body, url_map)
        
        # Build metadata
        metadata = {
            "article_id": article_id,
            "title": title,
            "source_url": f"https://support.contactsplus.com/hc/en-us/articles/{article_id}",
            "section_id": section_info.get("section_id"),
            "section_name": section_info.get("section_name"),
            "category_name": section_info.get("category_name"),
            "updated_at": None,
        }
        
        # Build Docmost-compatible HTML
        html_content = build_docmost_html(final_body, metadata)
        
        # Save HTML file
        html_filename = f"{title}.html"
        html_path = article_dir / html_filename
        html_path.write_text(html_content, encoding="utf-8")
        print(f"HTML saved: {html_path}")
        
        # Metadata dictionary (not saved to file)
        metadata_with_stats = {
            **metadata,
            "clean_stats": clean_stats,
            "downloaded_images": len(url_map),
            "image_count": len(image_urls),
            "iframe_count": len(iframe_urls_raw),
            "internal_link_count": len(internal_links),
        }
        
        # Create ZIP archive
        zip_path = self.output_dir / f"{sanitize_filename(title)}.zip"
        create_zip(article_dir, zip_path)
        print(f"ZIP created: {zip_path}")
        
        self.processed_articles.append({
            "article_id": article_id,
            "title": title,
            "url": metadata["source_url"],
            "image_count": len(image_urls),
            "iframe_count": len(iframe_urls_raw),
            "loom_embeds": clean_stats.get('loom_embeds', 0),
            "downloaded_images": len(url_map),
        })
        
        self.article_metadata[article_id] = metadata_with_stats
    
    def run(self, article_ids: list[str]):
        """Run the scraper for multiple articles."""
        print(f"Starting web scraper for {len(article_ids)} articles...")
        print(f"Output directory: {self.output_dir}\n")
        
        for i, article_id in enumerate(article_ids, 1):
            print(f"\n{'='*60}")
            print(f"Processing article {i}/{len(article_ids)}: {article_id}")
            print(f"{'='*60}")
            
            html_content = self.fetch_article_page(article_id)
            
            if html_content:
                self.process_article(article_id, html_content)
            else:
                print(f"SKIPPED: Could not fetch article {article_id}")
            
            # Be nice to the server
            if i < len(article_ids):
                time.sleep(2)
        
        # Save summary
        self.save_summary()
    
    def save_summary(self):
        """Print crawl summary (do not save to file)."""
        
        print(f"\n\n{'='*60}")
        print("SCRAPER SUMMARY")
        print(f"{'='*60}")
        print(f"Total articles processed: {len(self.processed_articles)}")
        print(f"\nProcessed articles:")
        for article in self.processed_articles:
            print(f"\n  Article ID: {article['article_id']}")
            print(f"  Title: {article['title']}")
            print(f"  URL: {article['url']}")
            print(f"  Images: {article['image_count']}")
            print(f"  Iframes: {article['iframe_count']}")
            print(f"  Loom embeds: {article['loom_embeds']}")
            print(f"  Downloaded images: {article['downloaded_images']}")
        print(f"{'='*60}\n")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Web scraper POC for Contacts+ Help Center"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="output/scrapy",
        help="Output directory for scraped articles",
    )
    args = parser.parse_args()
    
    # Test articles for POC
    test_article_ids = [
        "4407286476827",  # image-heavy
        "4406997562651",  # list/link-heavy
        "4410672626203",  # Loom embeds (Getting Started)
    ]
    
    scraper = ContactsPlusWebScraper(output_dir=args.output_dir)
    scraper.run(test_article_ids)


if __name__ == "__main__":
    main()
