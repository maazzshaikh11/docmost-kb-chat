#!/usr/bin/env python3
"""Manual recovery of the 2 accessible missing articles."""

import time
import requests
from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import unquote, urlparse

from migrate_article import (
    clean_html,
    download_images,
    extract_remote_images,
    rewrite_image_sources,
    sanitize_filename,
)

articles = [
    {
        'article_id': '4407220365851',
        'url': 'https://support.contactsplus.com/hc/en-us/articles/4407220365851-Blocking-spam-calls-and-SMS',
        'section': 'Managing Calls and SMS (Android only)',
    },
    {
        'article_id': '4407473676827',
        'url': 'https://support.contactsplus.com/hc/en-us/articles/4407473676827-Caller-ID-Hides-the-Call-Answer-Button-Android',
        'section': 'Troubleshooting',
    },
]

headers = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
}

output_dir = Path('output/full_migration')

for article_info in articles:
    print(f'\nProcessing {article_info["article_id"]}...')
    time.sleep(5)
    
    response = requests.get(article_info['url'], headers=headers, timeout=30)
    print(f'Status: {response.status_code}')
    
    if response.status_code != 200:
        print('FAILED')
        continue
    
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # Extract title
    h1 = soup.find('h1', class_='article-title')
    title = h1.get_text(strip=True) if h1 else f"Article {article_info['article_id']}"
    print(f'Title: {title}')
    
    # Extract article body
    article_body = soup.find('div', class_='article-body')
    if not article_body:
        print('No article body!')
        continue
    
    # Absolutize URLs
    base_url = 'https://support.contactsplus.com'
    for img in article_body.find_all('img', src=True):
        src = img['src']
        if src.startswith('/'):
            img['src'] = base_url + src
    
    article_body_html = str(article_body)
    
    # Clean HTML
    cleaned_body, clean_stats = clean_html(article_body_html)
    
    # Download images
    image_urls = extract_remote_images(cleaned_body)
    print(f'Images: {len(image_urls)}')
    
    section_dir = output_dir / sanitize_filename(article_info['section'])
    article_dir = section_dir / sanitize_filename(title)
    assets_dir = article_dir / 'assets'
    article_dir.mkdir(parents=True, exist_ok=True)
    
    url_map = {}
    if image_urls:
        assets_dir.mkdir(parents=True, exist_ok=True)
        for img_url in image_urls:
            try:
                time.sleep(2)
                img_resp = requests.get(img_url, timeout=60)
                img_resp.raise_for_status()
                
                path = unquote(urlparse(img_url).path)
                basename = Path(path).name
                filename = sanitize_filename(basename) if basename else 'image.png'
                
                destination = assets_dir / filename
                counter = 1
                while destination.exists():
                    stem = destination.stem
                    suffix = destination.suffix
                    destination = assets_dir / f'{stem}-{counter}{suffix}'
                    counter += 1
                
                destination.write_bytes(img_resp.content)
                url_map[img_url] = f'assets/{destination.name}'
            except Exception as e:
                print(f'Image failed: {e}')
    
    print(f'Downloaded: {len(url_map)} images')
    
    final_body = rewrite_image_sources(cleaned_body, url_map)
    
    # Build HTML
    metadata = {
        'article_id': article_info['article_id'],
        'title': title,
        'source_url': response.url,
        'section_name': article_info['section'],
    }
    
    comment_lines = [
        f"Source URL: {metadata['source_url']}",
        f"Section: {metadata['section_name']}",
        f"Article ID: {metadata['article_id']}",
    ]
    comment = '\n'.join(f'  {line}' for line in comment_lines)
    html_content = (
        '<!DOCTYPE html>\n'
        f'<html>\n<head>\n  <meta charset="utf-8">\n'
        f'  <title>{title}</title>\n  <!--\n{comment}\n  -->\n'
        f'</head>\n<body>\n{final_body}\n</body>\n</html>\n'
    )
    
    html_filename = f'{sanitize_filename(title)}.html'
    html_path = article_dir / html_filename
    html_path.write_text(html_content, encoding='utf-8')
    
    print(f'SUCCESS: {html_path}')

print('\nDone! Now rebuilding ZIP and validating...')

# Rebuild ZIP
import zipfile
zip_path = Path('output/Contacts_Plus_KB_Full_Migration.zip')
with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(output_dir.rglob("*")):
        if path.is_file():
            rel_path = path.relative_to(output_dir)
            archive.write(path, arcname=rel_path.as_posix())

print(f'ZIP created: {zip_path}')
print(f'ZIP size: {zip_path.stat().st_size / (1024*1024):.2f} MB')

# Final validation
html_files = list(output_dir.rglob("*.html"))
print(f'\nHTML files: {len(html_files)}')

import re
article_ids = set()
for html_file in html_files:
    content = html_file.read_text(encoding='utf-8')
    match = re.search(r'Article ID:\s*(\d+)', content)
    if match:
        article_ids.add(match.group(1))

print(f'Unique article IDs: {len(article_ids)}')
print(f'Target: 109')
print(f'Missing: {109 - len(article_ids)}')
