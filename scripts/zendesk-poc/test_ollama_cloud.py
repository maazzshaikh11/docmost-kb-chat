#!/usr/bin/env python3
"""
Test Ollama Cloud connectivity and discover available models.
"""

import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv


def test_ollama_cloud():
    """Test Ollama Cloud connection and list available models."""
    
    # Load environment variables from project root .env
    project_root = Path(__file__).parent.parent.parent
    dotenv_path = project_root / ".env"
    
    print(f"Loading environment from: {dotenv_path.resolve()}")
    
    if not dotenv_path.exists():
        print(f"\n❌ ERROR: .env file not found at {dotenv_path.resolve()}")
        print("\nPlease create a .env file at the project root with:")
        print("  OLLAMA_API_URL=https://ollama.com/api")
        print("  OLLAMA_API_KEY=<your-api-key>")
        print("  AI_EMBEDDING_MODEL=<to-be-determined>")
        print("  AI_COMPLETION_MODEL=<to-be-determined>")
        return 1
    
    load_dotenv(dotenv_path)
    
    # Get configuration
    ollama_url = os.getenv('OLLAMA_API_URL')
    ollama_key = os.getenv('OLLAMA_API_KEY')
    
    print(f"\n{'='*80}")
    print("OLLAMA CLOUD CONFIGURATION")
    print(f"{'='*80}")
    print(f"OLLAMA_API_URL: {ollama_url or '(not set)'}")
    print(f"OLLAMA_API_KEY: {'✓ configured' if ollama_key else '✗ NOT SET'}")
    print(f"{'='*80}\n")
    
    # Validate configuration
    if not ollama_url:
        print("❌ ERROR: OLLAMA_API_URL environment variable not set")
        print("\nAdd to .env:")
        print("  OLLAMA_API_URL=https://ollama.com/api")
        return 1
    
    if not ollama_key:
        print("❌ ERROR: OLLAMA_API_KEY environment variable not set")
        print("\nAdd to .env:")
        print("  OLLAMA_API_KEY=<your-ollama-api-key>")
        print("\nYou can create an API key at: https://ollama.com/settings/keys")
        return 1
    
    if ollama_url == 'http://localhost:11434':
        print("⚠️  WARNING: OLLAMA_API_URL is set to local Ollama")
        print("   For Ollama Cloud, use: https://ollama.com/api")
        print()
    
    # Test authentication and list models
    print("Testing Ollama Cloud connection...")
    print()
    
    headers = {
        'Authorization': f'Bearer {ollama_key}',
        'Content-Type': 'application/json',
    }
    
    try:
        # Try to list available models/tags
        response = requests.get(
            f"{ollama_url}/tags",
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 401:
            print("❌ ERROR: Authentication failed")
            print("   The OLLAMA_API_KEY is invalid or expired")
            print("   Please check your API key at: https://ollama.com/settings/keys")
            return 1
        
        if response.status_code == 403:
            print("❌ ERROR: Access forbidden")
            print("   The API key may not have the necessary permissions")
            return 1
        
        response.raise_for_status()
        data = response.json()
        
        print("✅ Successfully authenticated with Ollama Cloud")
        print()
        
        models = data.get('models', [])
        
        if not models:
            print("⚠️  No models found in your account")
            print("   You may need to pull models using the Ollama CLI")
            print("   Example: ollama pull llama3.2")
            return 1
        
        print(f"{'='*80}")
        print(f"AVAILABLE MODELS ({len(models)} total)")
        print(f"{'='*80}\n")
        
        # Categorize models
        embedding_models = []
        chat_models = []
        other_models = []
        
        embedding_keywords = ['embed', 'embedding', 'nomic', 'mxbai']
        
        for model in models:
            name = model.get('name', '')
            size = model.get('size', 0)
            size_gb = size / (1024**3) if size else 0
            
            # Categorize by name
            if any(keyword in name.lower() for keyword in embedding_keywords):
                embedding_models.append((name, size_gb))
            elif 'llama' in name.lower() or 'gpt' in name.lower() or 'mistral' in name.lower() or 'qwen' in name.lower():
                chat_models.append((name, size_gb))
            else:
                other_models.append((name, size_gb))
        
        # Display embedding models
        if embedding_models:
            print("EMBEDDING MODELS:")
            print("-" * 80)
            for name, size_gb in embedding_models:
                print(f"  • {name:<50} ({size_gb:.2f} GB)")
            print()
        
        # Display chat models
        if chat_models:
            print("CHAT/COMPLETION MODELS:")
            print("-" * 80)
            for name, size_gb in chat_models:
                print(f"  • {name:<50} ({size_gb:.2f} GB)")
            print()
        
        # Display other models
        if other_models:
            print("OTHER MODELS:")
            print("-" * 80)
            for name, size_gb in other_models:
                print(f"  • {name:<50} ({size_gb:.2f} GB)")
            print()
        
        # Recommendations
        print(f"{'='*80}")
        print("RECOMMENDATIONS")
        print(f"{'='*80}\n")
        
        # Recommend embedding model
        if embedding_models:
            recommended_embed = embedding_models[0][0]
            print(f"Embedding Model: {recommended_embed}")
            print(f"  Add to .env: AI_EMBEDDING_MODEL={recommended_embed}")
        else:
            print("⚠️  No embedding model found!")
            print("   Recommended: nomic-embed-text")
            print("   Pull it with: ollama pull nomic-embed-text")
            print("   Then add to .env: AI_EMBEDDING_MODEL=nomic-embed-text")
        
        print()
        
        # Recommend chat model
        if chat_models:
            # Prefer smaller, efficient models
            recommended_chat = chat_models[0][0]
            for name, size_gb in chat_models:
                if 'llama3.2' in name.lower() or 'llama3' in name.lower():
                    recommended_chat = name
                    break
            
            print(f"Chat Model: {recommended_chat}")
            print(f"  Add to .env: AI_COMPLETION_MODEL={recommended_chat}")
        else:
            print("⚠️  No chat model found!")
            print("   Recommended: llama3.2")
            print("   Pull it with: ollama pull llama3.2")
            print("   Then add to .env: AI_COMPLETION_MODEL=llama3.2")
        
        print()
        print(f"{'='*80}")
        print("NEXT STEPS")
        print(f"{'='*80}\n")
        
        if embedding_models and chat_models:
            print("1. Update .env with the recommended model names above")
            print("2. Run the indexer:")
            print("   python kb_indexer.py")
            print()
            print("3. Test chat:")
            print("   python kb_chat.py \"How do I sync my Google contacts?\"")
        else:
            print("1. Pull required models using Ollama CLI")
            print("2. Re-run this test to verify")
            print("3. Update .env with model names")
            print("4. Run the indexer")
        
        print()
        return 0
    
    except requests.exceptions.Timeout:
        print("❌ ERROR: Connection timeout")
        print("   Could not reach Ollama Cloud API")
        return 1
    
    except requests.exceptions.ConnectionError:
        print("❌ ERROR: Connection failed")
        print(f"   Could not connect to {ollama_url}")
        print("   Please check your internet connection and OLLAMA_API_URL")
        return 1
    
    except requests.exceptions.HTTPError as e:
        print(f"❌ ERROR: HTTP {e.response.status_code}")
        print(f"   {e.response.text}")
        return 1
    
    except Exception as e:
        print(f"❌ ERROR: {e}")
        return 1


if __name__ == "__main__":
    exit(test_ollama_cloud())
