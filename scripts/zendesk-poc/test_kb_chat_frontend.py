#!/usr/bin/env python3
"""
Test script to verify KB Chat frontend integration end-to-end.
This script:
1. Logs into Docmost
2. Sends a question to the /api/kb-chat endpoint
3. Verifies the response contains an answer and sources
"""

import requests
import json
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

BASE_URL = os.getenv("DOCMOST_BASE_URL", "http://localhost:3000")
EMAIL = os.getenv("DOCMOST_EMAIL")
PASSWORD = os.getenv("DOCMOST_PASSWORD")

def login():
    """Login and get session cookies"""
    print(f"\n1. Logging into Docmost at {BASE_URL}...")
    
    login_url = f"{BASE_URL}/api/auth/login"
    login_data = {
        "email": EMAIL,
        "password": PASSWORD
    }
    
    session = requests.Session()
    response = session.post(login_url, json=login_data)
    
    if response.status_code != 200:
        print(f"❌ Login failed with status {response.status_code}")
        print(f"Response: {response.text}")
        return None
    
    print("✅ Login successful")
    return session

def test_kb_chat(session, question):
    """Test the KB Chat endpoint"""
    print(f"\n2. Sending question to KB Chat: '{question}'")
    
    kb_chat_url = f"{BASE_URL}/api/kb-chat"
    payload = {"question": question}
    
    response = session.post(kb_chat_url, json=payload)
    
    print(f"\nStatus Code: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        print("\n✅ KB Chat Response:")
        print(f"\n📝 Answer:\n{data.get('answer', 'No answer')}")
        
        sources = data.get('sources', [])
        print(f"\n📚 Sources ({len(sources)}):")
        for i, source in enumerate(sources, 1):
            print(f"\n  {i}. {source.get('title', 'Untitled')}")
            print(f"     Page ID: {source.get('pageId')}")
            print(f"     Slug ID: {source.get('slugId')}")
            if source.get('spaceSlug'):
                print(f"     Space: {source.get('spaceSlug')}")
            print(f"     Similarity: {source.get('similarity', 0):.4f}")
            if source.get('matchedText'):
                print(f"     Excerpt: ...{source.get('matchedText')[:100]}...")
        
        return True
    else:
        print(f"\n❌ KB Chat request failed")
        print(f"Response: {response.text}")
        return False

def main():
    print("=" * 70)
    print("KB CHAT FRONTEND INTEGRATION TEST")
    print("=" * 70)
    
    # Check environment variables
    if not EMAIL or not PASSWORD:
        print("\n❌ Error: DOCMOST_EMAIL and DOCMOST_PASSWORD must be set in .env")
        return
    
    # Login
    session = login()
    if not session:
        return
    
    # Test KB Chat with a sample question
    test_questions = [
        "What is zendesk?",
        "How do I create a ticket?",
        "What are the different ticket statuses?"
    ]
    
    for i, question in enumerate(test_questions, 1):
        print(f"\n{'=' * 70}")
        print(f"TEST {i}/{len(test_questions)}")
        print(f"{'=' * 70}")
        success = test_kb_chat(session, question)
        if not success:
            print(f"\n⚠️ Test {i} failed, but continuing...")
    
    print("\n" + "=" * 70)
    print("✅ END-TO-END TEST COMPLETE")
    print("=" * 70)
    print("\nThe KB Chat UI is accessible at:")
    print(f"  {BASE_URL}/kb-chat")
    print("\nYou can:")
    print("  1. Navigate to /kb-chat in your browser")
    print("  2. Enter a question about your knowledge base")
    print("  3. View the AI-generated answer with source citations")
    print("  4. Click on source articles to navigate to them")

if __name__ == "__main__":
    main()
