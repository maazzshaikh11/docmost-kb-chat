#!/usr/bin/env python3
"""
Test retrieval independently from generation.
"""

import json
import pickle
from pathlib import Path

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer


def test_retrieval():
    """Test retrieval with sample queries."""
    
    index_dir = Path("output/kb_index")
    
    # Load index
    print("Loading index...")
    index = faiss.read_index(str(index_dir / "faiss.index"))
    
    with open(index_dir / "chunks.pkl", 'rb') as f:
        chunks = pickle.load(f)
    
    with open(index_dir / "config.json") as f:
        config = json.load(f)
    
    print(f"✓ Loaded {index.ntotal} vectors")
    print(f"✓ Embedding model: {config['embedding_model']}")
    print(f"✓ Total chunks: {len(chunks)}")
    print()
    
    # Load embedding model
    embedding_model = SentenceTransformer(config['embedding_model'])
    
    # Test queries
    test_queries = [
        "How do I sync my Google contacts?",
        "How can I export contacts?",
        "How do I delete my Contacts+ account?",
        "How do I turn off Caller ID?",
        "How do I scan a business card?",
        "What is the meaning of life?",  # Not in KB
    ]
    
    print(f"{'='*80}")
    print("RETRIEVAL TEST RESULTS")
    print(f"{'='*80}\n")
    
    for query in test_queries:
        print(f"QUERY: {query}")
        print("-" * 80)
        
        # Generate query embedding
        query_embedding = embedding_model.encode(query, convert_to_numpy=True).astype(np.float32)
        query_embedding = query_embedding.reshape(1, -1)
        
        # Normalize for cosine similarity
        faiss.normalize_L2(query_embedding)
        
        # Search
        scores, indices = index.search(query_embedding, 5)
        
        # Display results
        for i, (score, idx) in enumerate(zip(scores[0], indices[0])):
            if idx < len(chunks):
                chunk = chunks[idx]
                title = chunk['metadata'].get('title', 'Unknown')
                preview = chunk['text'][:150].replace('\n', ' ')
                print(f"{i+1}. [Score: {score:.4f}] {title}")
                print(f"   {preview}...")
                print()
        
        print()


if __name__ == "__main__":
    test_retrieval()
