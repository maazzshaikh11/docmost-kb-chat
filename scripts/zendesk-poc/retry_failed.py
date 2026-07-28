#!/usr/bin/env python3
"""
Retry only the failed articles from the full migration.
"""

import json
import time
from pathlib import Path

from full_migration import FullMigrationCrawler

# Failed article IDs from latest run - need to find their discovered URLs
FAILED_IDS = [
    "4407275141787",
    "4407286083739",
    "4407220365851",
    "4406998021531",
    "4407476247963",
    "4407475006107",
    "4407475802779",
    "47388245013403",
    "4407474813467",
    "4406972478875",
    "4411209966747",
    "4407476179611",
]


def main():
    print("\nRetrying failed articles...")
    print(f"{'='*60}\n")
    
    # Initialize crawler
    crawler = FullMigrationCrawler(output_dir="output/full_migration")
    
    # Give the server a rest
    print("Waiting 30 seconds to avoid rate limiting...")
    time.sleep(30)
    
    # Re-discover ALL articles to get URLs with slugs
    print("\nRe-discovering all articles to get proper URLs...")
    crawler.crawl_homepage()
    
    print(f"\nTotal articles discovered: {len(crawler.article_hierarchy)}")
    
    # Filter to only failed ones
    failed_articles = [
        a for a in crawler.article_hierarchy
        if a['article_id'] in FAILED_IDS
    ]
    
    print(f"Found {len(failed_articles)} failed articles to retry\n")
    
    if not failed_articles:
        print("No failed articles found in discovery!")
        return
    
    # Process only the failed articles
    for i, article_info in enumerate(failed_articles, 1):
        article_id = article_info['article_id']
        article_url = article_info['article_url']
        section_id = article_info['section_id']
        section_name = article_info['section_name']
        
        print(f"\n[{i}/{len(failed_articles)}] Retrying Article {article_id}")
        print(f"  URL: {article_url}")
        
        time.sleep(3)  # Extra delay for rate limiting
        
        try:
            crawler.process_article(
                article_id,
                article_url,
                section_id,
                section_name
            )
            print(f"  SUCCESS!")
        except Exception as e:
            print(f"  FAILED: {e}")
    
    # Recreate ZIP
    zip_path = crawler.create_final_zip()
    
    # Validate
    crawler.validate_output(zip_path)
    
    # Print summary
    crawler.print_summary(zip_path)


if __name__ == "__main__":
    main()
