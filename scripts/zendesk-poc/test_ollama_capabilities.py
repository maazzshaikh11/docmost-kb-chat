#!/usr/bin/env python3
"""
Test Ollama Cloud capabilities: embeddings and completion.
"""

import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv


def test_ollama_capabilities():
    """Test Ollama Cloud embedding and completion capabilities."""
    
    # Load environment variables
    project_root = Path(__file__).parent.parent.parent
    dotenv_path = project_root / ".env"
    load_dotenv(dotenv_path)
    
    ollama_url = os.getenv('OLLAMA_API_URL')
    ollama_key = os.getenv('OLLAMA_API_KEY')
    
    if not ollama_url or not ollama_key:
        print("❌ ERROR: OLLAMA_API_URL or OLLAMA_API_KEY not set")
        return 1
    
    headers = {
        'Authorization': f'Bearer {ollama_key}',
        'Content-Type': 'application/json',
    }
    
    print(f"{'='*80}")
    print("TESTING OLLAMA CLOUD CAPABILITIES")
    print(f"{'='*80}\n")
    
    # 1. List models
    print("1. Fetching available models...")
    try:
        response = requests.get(f"{ollama_url}/tags", headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        models = data.get('models', [])
        
        print(f"   Found {len(models)} models\n")
        
        models_list = models  # Store for later use
        
        # Check if any model names suggest embedding capability
        embedding_candidates = []
        chat_models = []
        
        for model in models:
            name = model.get('name', '')
            if any(keyword in name.lower() for keyword in ['embed', 'nomic', 'bge', 'mxbai']):
                embedding_candidates.append(name)
            else:
                chat_models.append(name)
        
        if embedding_candidates:
            print(f"   Potential embedding models: {embedding_candidates}")
        else:
            print("   ⚠️  No models with 'embed' in name found")
        
        print()
        
    except Exception as e:
        print(f"   ❌ Failed to list models: {e}\n")
        return 1
    
    # 2. Test embedding with correct /api/embed endpoint
    print("2. Testing embedding capability with /api/embed endpoint...")
    
    # Determine correct endpoint
    if ollama_url.endswith('/api'):
        embed_endpoint = f"{ollama_url}/embed"
    else:
        embed_endpoint = f"{ollama_url}/api/embed"
    
    print(f"   Endpoint: {embed_endpoint}\n")
    
    # Test models in order of priority
    test_models_for_embed = []
    
    # First, try common embedding model names (may not be in account but worth trying)
    common_embed_models = ['nomic-embed-text', 'embeddinggemma', 'qwen3-embedding', 'all-minilm']
    
    # Then try models actually in the account
    test_models_for_embed.extend(common_embed_models)
    test_models_for_embed.extend(chat_models[:5])  # Try first 5 chat models
    
    embedding_works = False
    working_embed_model = None
    test_results = []
    
    for test_model in test_models_for_embed:
        try:
            in_account = test_model in [m for m in models_list if test_model in m.get('name', '')]
            model_source = "in account" if in_account else "common name"
            
            print(f"   Testing: {test_model} ({model_source})")
            response = requests.post(
                embed_endpoint,
                json={
                    'model': test_model,
                    'input': 'Test embedding',
                },
                headers=headers,
                timeout=30
            )
            
            status = response.status_code
            
            if status == 200:
                result = response.json()
                # Check for embeddings in response (could be 'embedding' or 'embeddings')
                embedding_data = result.get('embedding') or (result.get('embeddings', [None])[0] if result.get('embeddings') else None)
                
                if embedding_data:
                    embedding_dim = len(embedding_data)
                    print(f"      ✅ SUCCESS: HTTP 200, dimension={embedding_dim}")
                    embedding_works = True
                    working_embed_model = test_model
                    test_results.append((test_model, status, f"SUCCESS, dim={embedding_dim}"))
                    break
                else:
                    msg = "HTTP 200 but no embedding in response"
                    print(f"      ⚠️  {msg}")
                    test_results.append((test_model, status, msg))
            else:
                error_msg = response.text[:150] if response.text else "No error message"
                print(f"      ❌ HTTP {status}: {error_msg}")
                test_results.append((test_model, status, error_msg))
        
        except requests.exceptions.Timeout:
            print(f"      ❌ Timeout")
            test_results.append((test_model, "timeout", "Request timeout"))
        except Exception as e:
            error = str(e)[:150]
            print(f"      ❌ Error: {error}")
            test_results.append((test_model, "error", error))
    
    print()
    
    if not embedding_works:
        print("   ❌ NO EMBEDDING MODEL FOUND")
        print("   Ollama Cloud may not support embeddings for this account")
        print()
    
    # 3. Test completion with gpt-oss:20b
    print("3. Testing completion with gpt-oss:20b...")
    
    gpt_20b_found = any('gpt-oss:20b' in m for m in chat_models)
    
    if not gpt_20b_found:
        print("   ⚠️  gpt-oss:20b not found in model list")
        print(f"   Available chat models: {chat_models[:5]}")
        test_model = chat_models[0] if chat_models else None
        if test_model:
            print(f"   Testing with {test_model} instead...")
    else:
        test_model = 'gpt-oss:20b'
    
    if not test_model:
        print("   ❌ No chat model available for testing")
        return 1
    
    # Determine correct endpoint
    if ollama_url.endswith('/api'):
        generate_endpoint = f"{ollama_url}/generate"
    else:
        generate_endpoint = f"{ollama_url}/api/generate"
    
    completion_works = False
    
    try:
        response = requests.post(
            generate_endpoint,
            json={
                'model': test_model,
                'prompt': 'Say "Hello from Ollama Cloud" and nothing else.',
                'stream': False,
            },
            headers=headers,
            timeout=60
        )
        
        if response.status_code == 200:
            result = response.json()
            answer = result.get('response', '').strip()
            print(f"   ✅ SUCCESS: {test_model} completion works")
            print(f"      Response: {answer[:100]}")
            completion_works = True
            print()
        else:
            print(f"   ❌ Failed: Status {response.status_code}")
            print(f"      {response.text[:200]}")
            print()
    
    except Exception as e:
        print(f"   ❌ Error: {e}")
        print()
    
    # 4. Summary and recommendations
    print(f"{'='*80}")
    print("DETAILED TEST RESULTS")
    print(f"{'='*80}\n")
    
    if test_results:
        print("Embedding tests:")
        for model, status, message in test_results[:10]:  # Show first 10
            print(f"  {model:30} | HTTP {str(status):4} | {message}")
        if len(test_results) > 10:
            print(f"  ... and {len(test_results) - 10} more tests")
        print()
    
    print(f"{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}\n")
    
    print(f"Ollama Cloud Embeddings: {'✅ SUPPORTED' if embedding_works else '❌ NOT AVAILABLE'}")
    if working_embed_model:
        print(f"Working Embedding Model: {working_embed_model}")
    
    print(f"Ollama Cloud Completion: {'✅ WORKING' if completion_works else '❌ FAILED'} (tested with {test_model})")
    print()
    
    print(f"{'='*80}")
    print("RECOMMENDATIONS")
    print(f"{'='*80}\n")
    
    if embedding_works:
        print("✅ Use Ollama Cloud for both embeddings and completion:")
        print(f"   AI_EMBEDDING_MODEL={working_embed_model}")
        print(f"   AI_COMPLETION_MODEL=gpt-oss:20b")
        print()
        print("Next step:")
        print("   python kb_indexer.py")
    else:
        print("⚠️  Ollama Cloud embeddings not available for this account")
        print()
        print("RECOMMENDED APPROACH:")
        print("   Use local sentence-transformers for embeddings (already installed)")
        print("   Use Ollama Cloud for completion only")
        print()
        print("   This approach:")
        print("   - Runs embeddings locally (no API calls)")
        print("   - Uses free, open-source model (all-MiniLM-L6-v2, 80MB)")
        print("   - Keeps answer generation on Ollama Cloud")
        print("   - Works for ~108 articles without performance issues")
        print()
        print("Next step:")
        print("   Modify kb_indexer.py to use sentence-transformers for embeddings")
    
    return 0


if __name__ == "__main__":
    exit(test_ollama_capabilities())
