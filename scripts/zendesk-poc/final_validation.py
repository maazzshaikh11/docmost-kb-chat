#!/usr/bin/env python3
"""
Final validation of the migration output.
"""

import re
import zipfile
from pathlib import Path
from collections import defaultdict

from bs4 import BeautifulSoup


def main():
    output_dir = Path("output/full_migration")
    zip_path = Path("output/Contacts_Plus_KB_Full_Migration.zip")
    
    print(f"\n{'='*80}")
    print("FINAL MIGRATION VALIDATION")
    print(f"{'='*80}\n")
    
    # Count actual HTML files
    html_files = list(output_dir.rglob("*.html"))
    print(f"HTML files generated: {len(html_files)}")
    
    # Count actual asset files
    asset_patterns = ["*.png", "*.jpg", "*.gif", "*.webp", "*.svg"]
    asset_files = []
    for pattern in asset_patterns:
        asset_files.extend(list(output_dir.rglob(pattern)))
    
    print(f"Asset files on disk: {len(asset_files)}")
    
    # Count assets in ZIP
    with zipfile.ZipFile(zip_path, 'r') as archive:
        zip_assets = [name for name in archive.namelist() 
                      if any(name.endswith(ext) for ext in ['.png', '.jpg', '.gif', '.webp', '.svg'])]
        print(f"Asset files in ZIP: {len(zip_assets)}")
        print(f"Total files in ZIP: {len(archive.namelist())}")
    
    # Extract article IDs from HTML files
    article_ids = set()
    section_counts = defaultdict(int)
    
    for html_file in html_files:
        # Parse HTML to extract article ID from comment
        content = html_file.read_text(encoding='utf-8')
        soup = BeautifulSoup(content, 'html.parser')
        
        # Find article ID in comment
        for comment in soup.find_all(string=lambda text: isinstance(text, str) and 'Article ID:' in text):
            match = re.search(r'Article ID:\s*(\d+)', comment)
            if match:
                article_ids.add(match.group(1))
        
        # Count by section
        section_name = html_file.parent.parent.name
        section_counts[section_name] += 1
    
    print(f"\nUnique article IDs in generated HTML: {len(article_ids)}")
    
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
    
    print(f"Broken local asset references: {len(broken_refs)}")
    
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
    
    # Count Loom embeds
    loom_embeds = 0
    for html_file in html_files:
        content = html_file.read_text(encoding='utf-8')
        soup = BeautifulSoup(content, 'html.parser')
        loom_divs = soup.find_all('div', attrs={'data-type': 'embed', 'data-provider': 'loom'})
        loom_embeds += len(loom_divs)
    
    print(f"Loom embeds converted: {loom_embeds}")
    
    # Count internal KB links
    internal_links = 0
    for html_file in html_files:
        content = html_file.read_text(encoding='utf-8')
        soup = BeautifulSoup(content, 'html.parser')
        for link in soup.find_all('a', href=True):
            href = link['href']
            if '/articles/' in href and 'contactsplus.com' in href:
                internal_links += 1
    
    print(f"Internal KB links found: {internal_links}")
    
    # Section breakdown
    print(f"\n{'='*80}")
    print("SECTION BREAKDOWN")
    print(f"{'='*80}\n")
    
    for section, count in sorted(section_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"  {section}: {count} articles")
    
    # ZIP integrity
    print(f"\n{'='*80}")
    print("ZIP INTEGRITY")
    print(f"{'='*80}\n")
    
    try:
        with zipfile.ZipFile(zip_path, 'r') as archive:
            bad_file = archive.testzip()
            if bad_file:
                print(f"ZIP integrity: FAILED - {bad_file}")
            else:
                print(f"ZIP integrity: OK ✓")
                print(f"ZIP size: {zip_path.stat().st_size / (1024*1024):.2f} MB")
    except Exception as e:
        print(f"ZIP integrity: ERROR - {e}")
    
    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}\n")
    
    print(f"Total HTML articles: {len(html_files)}")
    print(f"Unique article IDs: {len(article_ids)}")
    print(f"Total assets: {len(asset_files)}")
    print(f"Broken asset references: {len(broken_refs)}")
    print(f"Remote image references: {len(remote_refs)}")
    print(f"Loom embeds: {loom_embeds}")
    print(f"Internal KB links: {internal_links}")
    print(f"\nZIP path: {zip_path}")
    print(f"ZIP size: {zip_path.stat().st_size / (1024*1024):.2f} MB")
    
    # List article IDs (first 20)
    print(f"\n{'='*80}")
    print("SAMPLE ARTICLE IDs (first 20)")
    print(f"{'='*80}\n")
    
    for aid in sorted(list(article_ids))[:20]:
        print(f"  {aid}")
    
    if len(article_ids) > 20:
        print(f"  ... and {len(article_ids) - 20} more")
    
    print(f"\n{'='*80}\n")


if __name__ == "__main__":
    main()
