#!/usr/bin/env python3
"""
Investigate failed articles from the full migration.
"""

import json
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# Failed article IDs
FAILED_ARTICLE_IDS = [
    "4407472637595",
    "4407475782939",
    "4407476280475",
    "4407464475291",
    "4407462789531",
    "4407275141787",
    "4406997441691",
    "4407214797595",
    "4407221781019",
]

BASE_URL = "https://support.contactsplus.com"
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
}


def investigate_article(article_id: str, discovered_url: str | None = None):
    """Investigate a single failed article."""
    print(f"\n{'='*80}")
    print(f"Investigating Article ID: {article_id}")
    print(f"{'='*80}")
    
    results = {
        'article_id': article_id,
        'discovered_url': discovered_url,
        'constructed_url': None,
        'http_status': None,
        'redirect_chain': [],
        'final_url': None,
        'content_length': None,
        'actual_cause': None,
        'title': None,
        'has_body': False,
    }
    
    # If we don't have the discovered URL, we need to find it
    if not discovered_url:
        print("  Discovered URL not available, will search sections")
        discovered_url = find_article_in_sections(article_id)
        results['discovered_url'] = discovered_url
    
    if not discovered_url:
        # Try constructed URL as fallback
        constructed_url = f"{BASE_URL}/hc/en-us/articles/{article_id}"
        print(f"  Trying constructed URL: {constructed_url}")
        results['constructed_url'] = constructed_url
        discovered_url = constructed_url
    
    print(f"  Testing URL: {discovered_url}")
    
    # Make request with redirect tracking
    try:
        session = requests.Session()
        response = session.get(
            discovered_url,
            headers=HEADERS,
            timeout=30,
            allow_redirects=True
        )
        
        # Track redirect chain
        if response.history:
            print(f"  Redirect chain:")
            for i, redirect in enumerate(response.history, 1):
                print(f"    {i}. {redirect.status_code} -> {redirect.url}")
                results['redirect_chain'].append({
                    'status': redirect.status_code,
                    'url': redirect.url
                })
        
        results['http_status'] = response.status_code
        results['final_url'] = response.url
        results['content_length'] = len(response.text)
        
        print(f"  Status: {response.status_code}")
        print(f"  Final URL: {response.url}")
        print(f"  Content length: {len(response.text)} bytes")
        
        if response.status_code == 200:
            # Parse and check for content
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Extract title
            title_tag = soup.find('h1', class_='article-title') or soup.find('h1')
            if title_tag:
                title = title_tag.get_text(strip=True)
                if '|' in title:
                    title = title.split('|')[0].strip()
                results['title'] = title
                print(f"  Title: {title}")
            
            # Check for article body
            article_body = soup.find('div', class_='article-body') or soup.find('article', class_='article')
            if article_body:
                body_text = article_body.get_text(strip=True)
                results['has_body'] = len(body_text) > 0
                print(f"  Has body content: {results['has_body']}")
                print(f"  Body length: {len(body_text)} chars")
            else:
                print(f"  WARNING: No article body found")
                results['actual_cause'] = "Article body not found in HTML"
        
        elif response.status_code == 404:
            results['actual_cause'] = "404 Not Found - Article deleted or URL incorrect"
            print(f"  CAUSE: 404 Not Found")
        
        elif response.status_code == 403:
            results['actual_cause'] = "403 Forbidden - Access denied"
            print(f"  CAUSE: 403 Forbidden")
        
        else:
            results['actual_cause'] = f"HTTP {response.status_code}"
            print(f"  CAUSE: HTTP {response.status_code}")
    
    except requests.Timeout:
        results['actual_cause'] = "Request timeout"
        print(f"  CAUSE: Request timeout")
    
    except requests.RequestException as e:
        results['actual_cause'] = f"Request error: {str(e)}"
        print(f"  CAUSE: {e}")
    
    return results


def find_article_in_sections(article_id: str) -> str | None:
    """Search for article in all sections to find its discovered URL."""
    print(f"  Searching for article {article_id} in sections...")
    
    # Get homepage
    try:
        response = requests.get(f"{BASE_URL}/hc/en-us", headers=HEADERS, timeout=30)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Find section links
        section_links = []
        for selector in ['a[href*="/sections/"]']:
            found = soup.select(selector)
            section_links.extend([a.get('href') for a in found if a.get('href')])
        
        section_links = list(set(section_links))
        
        # Search each section
        for link in section_links:
            section_match = re.search(r'/sections/(\d+)', link)
            if not section_match:
                continue
            
            section_id = section_match.group(1)
            section_url = f"{BASE_URL}{link}" if link.startswith('/') else link
            
            time.sleep(2)  # Be polite
            
            try:
                sec_response = requests.get(section_url, headers=HEADERS, timeout=30)
                sec_soup = BeautifulSoup(sec_response.text, 'html.parser')
                
                # Find article links
                for a in sec_soup.select('a[href*="/articles/"]'):
                    href = a.get('href')
                    if f'/articles/{article_id}' in href:
                        full_url = f"{BASE_URL}{href}" if href.startswith('/') else href
                        print(f"    Found in section {section_id}: {full_url}")
                        return full_url
            
            except Exception as e:
                print(f"    Error checking section {section_id}: {e}")
                continue
    
    except Exception as e:
        print(f"  Error searching sections: {e}")
    
    return None


def main():
    print(f"\n{'='*80}")
    print("INVESTIGATING FAILED ARTICLES")
    print(f"{'='*80}\n")
    
    all_results = []
    
    # First, try to get discovered URLs from migration log
    discovered_urls = {}
    
    # Check if we have the article hierarchy from a previous run
    # For now, we'll search for each one
    
    for article_id in FAILED_ARTICLE_IDS:
        time.sleep(2)  # Be polite
        result = investigate_article(article_id)
        all_results.append(result)
    
    # Print summary table
    print(f"\n{'='*80}")
    print("INVESTIGATION SUMMARY")
    print(f"{'='*80}\n")
    
    print(f"{'Article ID':<15} {'HTTP':<6} {'Has Body':<10} {'Cause':<50}")
    print(f"{'-'*15} {'-'*6} {'-'*10} {'-'*50}")
    
    recoverable = 0
    for result in all_results:
        article_id = result['article_id']
        status = result['http_status'] or 'N/A'
        has_body = 'Yes' if result['has_body'] else 'No'
        cause = result['actual_cause'] or 'Unknown'
        
        print(f"{article_id:<15} {str(status):<6} {has_body:<10} {cause:<50}")
        
        if result['http_status'] == 200 and result['has_body']:
            recoverable += 1
    
    print(f"\n{'='*80}")
    print(f"Recoverable articles: {recoverable} out of {len(FAILED_ARTICLE_IDS)}")
    print(f"{'='*80}\n")
    
    # Print detailed results
    print("\nDETAILED RESULTS:\n")
    for result in all_results:
        print(f"\nArticle {result['article_id']}:")
        print(f"  Discovered URL: {result['discovered_url']}")
        print(f"  HTTP Status: {result['http_status']}")
        print(f"  Final URL: {result['final_url']}")
        print(f"  Title: {result['title']}")
        print(f"  Has Body: {result['has_body']}")
        print(f"  Actual Cause: {result['actual_cause']}")
        if result['redirect_chain']:
            print(f"  Redirects: {len(result['redirect_chain'])}")
    
    return all_results


if __name__ == "__main__":
    main()
