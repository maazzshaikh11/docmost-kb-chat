#!/usr/bin/env python3
"""
Final conservative recovery pass for the 3 missing articles.
"""

import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from migrate_article import (
    clean_html,
    download_images,
    extract_remote_images,
    rewrite_image_sources,
    sanitize_filename,
)


def identify_missing_articles():
    """Identify the 3 missing articles by comparing discovered vs generated."""
    output_dir = Path("output/full_migration")
    
    print(f"\n{'='*80}")
    print("IDENTIFYING MISSING ARTICLES")
    print(f"{'='*80}\n")
    
    # Get all discovered article IDs from the last full crawl
    # We need to re-discover to get the full list
    print("Re-discovering all articles to get the complete list...")
    
    from full_migration import FullMigrationCrawler
    crawler = FullMigrationCrawler(output_dir="output/full_migration")
    
    print("\nCrawling homepage to discover all articles...")
    crawler.crawl_homepage()
    
    discovered_ids = set(a['article_id'] for a in crawler.article_hierarchy)
    print(f"Discovered article IDs: {len(discovered_ids)}")
    
    # Get generated article IDs from HTML files
    html_files = list(output_dir.rglob("*.html"))
    generated_ids = set()
    
    for html_file in html_files:
        content = html_file.read_text(encoding='utf-8')
        match = re.search(r'Article ID:\s*(\d+)', content)
        if match:
            generated_ids.add(match.group(1))
    
    print(f"Generated article IDs: {len(generated_ids)}")
    
    # Find missing
    missing_ids = discovered_ids - generated_ids
    print(f"Missing article IDs: {len(missing_ids)}")
    
    if not missing_ids:
        print("\nNo missing articles!")
        return [], crawler
    
    # Get full info for missing articles
    missing_articles = [
        a for a in crawler.article_hierarchy
        if a['article_id'] in missing_ids
    ]
    
    print(f"\n{'='*80}")
    print("MISSING ARTICLES")
    print(f"{'='*80}\n")
    
    for article in missing_articles:
        print(f"ID: {article['article_id']}")
        print(f"  Section: {article['section_name']}")
        print(f"  URL: {article['article_url']}")
        print()
    
    return missing_articles, crawler


def recover_article(article_info: dict, session: requests.Session, output_dir: Path, 
                    attempt_num: int = 1, max_attempts: int = 5) -> bool:
    """
    Attempt to recover a single article with conservative retry.
    Returns True if successful.
    """
    article_id = article_info['article_id']
    article_url = article_info['article_url']
    section_id = article_info['section_id']
    section_name = article_info['section_name']
    
    print(f"\n{'='*80}")
    print(f"Attempt {attempt_num}/{max_attempts}: Article {article_id}")
    print(f"{'='*80}")
    print(f"URL: {article_url}")
    
    # Conservative delay: 5-10 seconds, increasing with attempts
    delay = 5 + (attempt_num - 1) * 5
    if attempt_num > 1:
        print(f"Waiting {delay} seconds before retry...")
        time.sleep(delay)
    else:
        print(f"Waiting {delay} seconds...")
        time.sleep(delay)
    
    try:
        response = session.get(
            article_url,
            timeout=30,
            allow_redirects=True
        )
        
        print(f"HTTP Status: {response.status_code}")
        print(f"Final URL: {response.url}")
        print(f"Content length: {len(response.text)} bytes")
        
        if response.status_code != 200:
            print(f"FAILED: HTTP {response.status_code}")
            
            if attempt_num < max_attempts:
                return recover_article(article_info, session, output_dir, attempt_num + 1, max_attempts)
            else:
                print(f"GIVING UP after {max_attempts} attempts")
                return False
        
        # Parse HTML - extract what we need FIRST before any modifications
        html_content = response.text
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Extract title
        title = None
        for selector in [('h1', 'article-title'), ('h1', None)]:
            tag_name, class_name = selector
            title_tag = soup.find(tag_name, class_=class_name) if class_name else soup.find(tag_name)
            if title_tag:
                title = title_tag.get_text(strip=True)
                if '|' in title:
                    title = title.split('|')[0].strip()
                if title:
                    break
        
        if not title:
            title_tag = soup.find('title')
            if title_tag:
                title = title_tag.get_text(strip=True)
                if '|' in title:
                    title = title.split('|')[0].strip()
        
        if not title:
            title = f"Article {article_id}"
        
        print(f"Title: {title}")
        
        # Extract article body HTML BEFORE any modifications
        article_body = None
        for tag_name, class_name in [('div', 'article-body'), ('article', 'article')]:
            article_body = soup.find(tag_name, class_=class_name) if class_name else soup.find(tag_name)
            if article_body:
                break
        
        if not article_body:
            print("FAILED: No article body found in HTML")
        
        # Get article body HTML as string
        article_body_html = str(article_body)
        body_text = article_body.get_text(strip=True)
        print(f"Article body found: {len(body_text)} chars")
        
        # NOW absolutize URLs in the HTML string
        base_url = "https://support.contactsplus.com"
        soup2 = BeautifulSoup(article_body_html, 'html.parser')
        for img in soup2.find_all("img", src=True):
            src = img["src"]
            if src.startswith("/"):
                img["src"] = base_url + src
            elif not src.startswith(("http://", "https://")):
                from urllib.parse import urljoin
                img["src"] = urljoin(base_url + "/hc/en-us/", src)
        article_body_html = str(soup2)
        
        # Process through transformation pipeline
        print("Cleaning HTML...")
        cleaned_body, clean_stats = clean_html(article_body_html)
        
        print(f"Loom embeds: {clean_stats.get('loom_embeds', 0)}")
        
        # Extract and download images
        image_urls = extract_remote_images(cleaned_body)
        print(f"Images to download: {len(image_urls)}")
        
        # Create directories
        section_dir = output_dir / sanitize_filename(section_name)
        article_dir = section_dir / sanitize_filename(title)
        assets_dir = article_dir / "assets"
        article_dir.mkdir(parents=True, exist_ok=True)
        
        # Download images
        url_map = {}
        if image_urls:
            assets_dir.mkdir(parents=True, exist_ok=True)
            print("Downloading images...")
            
            for img_url in image_urls:
                try:
                    time.sleep(2)  # Be polite
                    img_response = session.get(img_url, timeout=60)
                    img_response.raise_for_status()
                    
                    # Determine filename
                    from urllib.parse import unquote, urlparse
                    path = unquote(urlparse(img_url).path)
                    basename = Path(path).name
                    if basename:
                        filename = sanitize_filename(basename)
                    else:
                        filename = "image.png"
                    
                    # Infer extension if needed
                    if '.' not in filename or filename.endswith('.'):
                        content_type = img_response.headers.get('Content-Type', '').split(';')[0].strip().lower()
                        mime_to_ext = {
                            'image/png': '.png',
                            'image/jpeg': '.jpg',
                            'image/jpg': '.jpg',
                            'image/gif': '.gif',
                            'image/webp': '.webp',
                            'image/svg+xml': '.svg',
                        }
                        ext = mime_to_ext.get(content_type, '.png')
                        
                        path_parts = urlparse(img_url).path.split('/')
                        numeric_id = next((part for part in reversed(path_parts) if part.isdigit()), None)
                        if numeric_id:
                            filename = f"{numeric_id}{ext}"
                        else:
                            filename = f"image-{abs(hash(img_url)) % 10000}{ext}"
                    
                    destination = assets_dir / filename
                    
                    # Handle duplicates
                    counter = 1
                    while destination.exists():
                        stem = destination.stem
                        suffix = destination.suffix
                        destination = assets_dir / f"{stem}-{counter}{suffix}"
                        counter += 1
                    
                    destination.write_bytes(img_response.content)
                    url_map[img_url] = f"assets/{destination.name}"
                    
                except Exception as e:
                    print(f"  Warning: Failed to download {img_url}: {e}")
        
        print(f"Images downloaded: {len(url_map)}")
        
        # Rewrite image sources
        final_body = rewrite_image_sources(cleaned_body, url_map)
        
        # Build metadata
        metadata = {
            "article_id": article_id,
            "title": title,
            "source_url": response.url,
            "section_id": section_id,
            "section_name": section_name,
            "updated_at": None,
        }
        
        # Build HTML
        comment_lines = [
            f"Source URL: {metadata['source_url']}",
            f"Section ID: {metadata['section_id']}",
            f"Section: {metadata['section_name']}",
            f"Article ID: {metadata['article_id']}",
        ]
        comment = "\n".join(f"  {line}" for line in comment_lines)
        html_content = (
            "<!DOCTYPE html>\n"
            f"<html>\n<head>\n  <meta charset=\"utf-8\">\n"
            f"  <title>{title}</title>\n  <!--\n{comment}\n  -->\n"
            f"</head>\n<body>\n{final_body}\n</body>\n</html>\n"
        )
        
        # Save HTML
        html_filename = f"{sanitize_filename(title)}.html"
        html_path = article_dir / html_filename
        html_path.write_text(html_content, encoding="utf-8")
        
        print(f"SUCCESS: Saved to {html_path}")
        return True
        
    except requests.Timeout:
        print(f"FAILED: Request timeout")
        
        if attempt_num < max_attempts:
            return recover_article(article_info, session, output_dir, attempt_num + 1, max_attempts)
        else:
            print(f"GIVING UP after {max_attempts} attempts")
            return False
            
    except Exception as e:
        print(f"FAILED: {e}")
        
        if attempt_num < max_attempts:
            return recover_article(article_info, session, output_dir, attempt_num + 1, max_attempts)
        else:
            print(f"GIVING UP after {max_attempts} attempts")
            return False


def rebuild_final_zip(output_dir: Path) -> Path:
    """Rebuild the final ZIP from all generated articles."""
    import zipfile
    
    zip_path = output_dir.parent / "Contacts_Plus_KB_Full_Migration.zip"
    
    print(f"\n{'='*80}")
    print("REBUILDING FINAL ZIP")
    print(f"{'='*80}\n")
    
    with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(output_dir.rglob("*")):
            if path.is_file():
                rel_path = path.relative_to(output_dir)
                archive.write(path, arcname=rel_path.as_posix())
    
    print(f"ZIP created: {zip_path}")
    print(f"ZIP size: {zip_path.stat().st_size / (1024*1024):.2f} MB")
    
    return zip_path


def validate_final_output(output_dir: Path, zip_path: Path, discovered_count: int):
    """Final validation."""
    print(f"\n{'='*80}")
    print("FINAL VALIDATION")
    print(f"{'='*80}\n")
    
    # Count HTML files
    html_files = list(output_dir.rglob("*.html"))
    print(f"HTML files: {len(html_files)}")
    
    # Extract article IDs
    article_ids = set()
    for html_file in html_files:
        content = html_file.read_text(encoding='utf-8')
        match = re.search(r'Article ID:\s*(\d+)', content)
        if match:
            article_ids.add(match.group(1))
    
    print(f"Unique article IDs: {len(article_ids)}")
    print(f"Discovered articles: {discovered_count}")
    print(f"Missing: {discovered_count - len(article_ids)}")
    
    # Duplicates
    from collections import Counter
    id_counts = Counter()
    for html_file in html_files:
        content = html_file.read_text(encoding='utf-8')
        match = re.search(r'Article ID:\s*(\d+)', content)
        if match:
            id_counts[match.group(1)] += 1
    
    duplicates = {aid: count for aid, count in id_counts.items() if count > 1}
    print(f"Duplicate IDs: {len(duplicates)}")
    
    # Count assets
    asset_files = []
    for pattern in ["*.png", "*.jpg", "*.gif", "*.webp", "*.svg"]:
        asset_files.extend(list(output_dir.rglob(pattern)))
    print(f"Unique assets: {len(asset_files)}")
    
    # Check broken references
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
    
    print(f"Broken asset references: {len(broken_refs)}")
    
    # Check remote references
    remote_refs = []
    for html_file in html_files:
        content = html_file.read_text(encoding='utf-8')
        soup = BeautifulSoup(content, 'html.parser')
        for img in soup.find_all('img', src=True):
            src = img['src']
            if src.startswith(('http://', 'https://')):
                remote_refs.append((html_file.name, src))
    
    print(f"Remote image references: {len(remote_refs)}")
    
    # ZIP integrity
    import zipfile
    try:
        with zipfile.ZipFile(zip_path, 'r') as archive:
            bad_file = archive.testzip()
            if bad_file:
                print(f"ZIP integrity: FAILED - {bad_file}")
            else:
                print(f"ZIP integrity: OK ✓")
    except Exception as e:
        print(f"ZIP integrity: ERROR - {e}")
    
    return {
        'html_count': len(html_files),
        'unique_ids': len(article_ids),
        'duplicates': len(duplicates),
        'assets': len(asset_files),
        'broken_refs': len(broken_refs),
        'remote_refs': len(remote_refs),
    }


def main():
    output_dir = Path("output/full_migration")
    
    # Step 1: Identify missing articles
    missing_articles, crawler = identify_missing_articles()
    
    if not missing_articles:
        print("No missing articles to recover!")
        return
    
    print(f"\n{'='*80}")
    print(f"RECOVERING {len(missing_articles)} MISSING ARTICLES")
    print(f"{'='*80}\n")
    
    # Step 2: Create persistent session with browser-like headers
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate, br',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    })
    
    # Step 3: Recover each article
    recovery_results = []
    for article_info in missing_articles:
        success = recover_article(article_info, session, output_dir, attempt_num=1, max_attempts=5)
        recovery_results.append({
            'article_id': article_info['article_id'],
            'section': article_info['section_name'],
            'url': article_info['article_url'],
            'success': success,
        })
    
    # Step 4: Rebuild ZIP
    zip_path = rebuild_final_zip(output_dir)
    
    # Step 5: Validate
    validation = validate_final_output(output_dir, zip_path, len(crawler.article_hierarchy))
    
    # Step 6: Report
    print(f"\n{'='*80}")
    print("RECOVERY REPORT")
    print(f"{'='*80}\n")
    
    print("Missing articles attempted:")
    for result in recovery_results:
        status = "✓ RECOVERED" if result['success'] else "✗ FAILED"
        print(f"\n{status}")
        print(f"  ID: {result['article_id']}")
        print(f"  Section: {result['section']}")
        print(f"  URL: {result['url']}")
    
    recovered_count = sum(1 for r in recovery_results if r['success'])
    
    print(f"\n{'='*80}")
    print("FINAL RESULTS")
    print(f"{'='*80}\n")
    
    print(f"Missing articles: {len(missing_articles)}")
    print(f"Recovered: {recovered_count}")
    print(f"Still missing: {len(missing_articles) - recovered_count}")
    print(f"\nFinal migrated count: {validation['html_count']} / {len(crawler.article_hierarchy)}")
    print(f"Unique asset count: {validation['assets']}")
    print(f"Broken asset references: {validation['broken_refs']}")
    print(f"Remote image references: {validation['remote_refs']}")
    print(f"Duplicate article IDs: {validation['duplicates']}")
    print(f"\nFinal ZIP: {zip_path}")
    print(f"ZIP size: {zip_path.stat().st_size / (1024*1024):.2f} MB")
    
    if validation['html_count'] < len(crawler.article_hierarchy):
        still_missing = len(crawler.article_hierarchy) - validation['html_count']
        print(f"\n{'='*80}")
        print(f"UNRESOLVED: {still_missing} articles still missing")
        print(f"{'='*80}")
    
    print(f"\n{'='*80}\n")


if __name__ == "__main__":
    main()
