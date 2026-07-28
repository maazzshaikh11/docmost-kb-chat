#!/usr/bin/env python3
"""
Knowledge Base Chat CLI for RAG.

Retrieves relevant KB chunks and generates answers using Ollama.
"""

import argparse
import json
import os
import pickle
from pathlib import Path

import faiss
import numpy as np
import requests
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer

from citation_utils import process_citations


class KBChat:
    """Chat interface for knowledge base queries."""
    
    def __init__(self, index_dir: str = "output/kb_index", debug: bool = False):
        self.index_dir = Path(index_dir)
        self.debug = debug
        
        # Load environment variables from project root .env
        project_root = Path(__file__).parent.parent.parent
        dotenv_path = project_root / ".env"
        load_dotenv(dotenv_path)
        
        # Load configuration
        config_path = self.index_dir / "config.json"
        if not config_path.exists():
            raise FileNotFoundError(f"Index not found at {self.index_dir}. Run kb_indexer.py first.")
        
        with open(config_path) as f:
            self.config = json.load(f)
        
        # Load sentence-transformers for embeddings
        embedding_model_name = self.config.get('embedding_model', 'all-MiniLM-L6-v2')
        if self.debug:
            print(f"Loading embedding model: {embedding_model_name}")
        self.embedding_model = SentenceTransformer(embedding_model_name)
        
        # Ollama Cloud for completion
        self.ollama_url = os.getenv('OLLAMA_API_URL', 'https://ollama.com/api')
        self.ollama_key = os.getenv('OLLAMA_API_KEY')
        self.completion_model = os.getenv('AI_COMPLETION_MODEL', 'gpt-oss:20b')
        
        if self.debug:
            print(f"Ollama URL: {self.ollama_url}")
            print(f"Ollama API Key: {'✓ configured' if self.ollama_key else '✗ NOT SET'}")
            print(f"Completion model: {self.completion_model}")
        
        if not self.ollama_key:
            print("\n⚠️  WARNING: OLLAMA_API_KEY is not set")
            print("   Answer generation will fail")
        
        # Load FAISS index
        index_path = self.index_dir / "faiss.index"
        self.index = faiss.read_index(str(index_path))
        
        # Load chunks
        chunks_path = self.index_dir / "chunks.pkl"
        with open(chunks_path, 'rb') as f:
            self.chunks = pickle.load(f)
        
        if self.debug:
            print(f"Loaded index with {self.index.ntotal} vectors")
            print(f"Loaded {len(self.chunks)} chunks")
    
    def generate_embedding(self, text: str) -> np.ndarray:
        """Generate embedding using sentence-transformers."""
        embedding = self.embedding_model.encode(text, convert_to_numpy=True)
        return embedding.astype(np.float32)
    
    def retrieve(self, query: str, top_k: int = 5) -> list[dict]:
        """Retrieve top-k most relevant chunks."""
        # Generate query embedding
        query_embedding = self.generate_embedding(query)
        query_embedding = query_embedding.reshape(1, -1)
        
        # Normalize for cosine similarity
        faiss.normalize_L2(query_embedding)
        
        # Search
        scores, indices = self.index.search(query_embedding, top_k)
        
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < len(self.chunks):
                chunk = self.chunks[idx].copy()
                chunk['score'] = float(score)
                results.append(chunk)
        
        return results
    
    def generate_answer(self, query: str, context_chunks: list[dict]) -> dict:
        """Generate answer using Ollama completion."""
        unique_sources = []
        source_map = {}  # mapping from (title, article_id) -> 1-based index

        for chunk in context_chunks:
            meta = chunk["metadata"]
            title = meta.get("title", "Unknown Article")
            article_id = meta.get("article_id")
            
            # Use article_id as primary key if available, else title
            key = article_id if article_id else title
            
            if key not in source_map:
                unique_sources.append({
                    'title': title,
                    'article_id': article_id,
                    'source_url': meta.get('source_url'),
                    'section': meta.get('section'),
                })
                source_map[key] = len(unique_sources)

        context_parts = []
        for chunk in context_chunks:
            meta = chunk["metadata"]
            title = meta.get("title", "Unknown Article")
            article_id = meta.get("article_id")
            key = article_id if article_id else title
            citation_num = source_map[key]
            
            text = chunk["text"]
            context_parts.append(f"[{citation_num}] {title}\n{text}\n")

        context = "\n".join(context_parts)
        
        # Build prompt
        prompt = f"""You are a helpful assistant for Contacts+ Knowledge Base support.

Answer the user's question using ONLY the information provided in the context below.

IMPORTANT RULES:
1. Answer ONLY from the provided context
2. If the context does not contain enough information, say "I don't have enough information in the knowledge base to answer this question."
3. Do NOT invent or assume information
4. Be concise and direct
5. You MUST include inline citations immediately after each supported claim using the bracketed numbers from the context (e.g. [1], [2]).
6. Do NOT repeat the same citation consecutively. Output [1] instead of [1][1] or [1] [1].
7. Combine different citations without spaces if multiple sources support the same claim: [1][2].
8. Do NOT output a separate "Sources: [1]" list or sentence at the end of your answer. Include citations inline only.
9. You do not need to cite every provided source, only the ones you actually use.

CONTEXT:
{context}

USER QUESTION: {query}

ANSWER:"""

        headers = {'Content-Type': 'application/json'}
        
        # Add authentication for Ollama Cloud
        if self.ollama_key:
            headers['Authorization'] = f'Bearer {self.ollama_key}'
        
        # Call Ollama Cloud
        if self.ollama_url.endswith('/api'):
            generate_endpoint = f"{self.ollama_url}/generate"
        else:
            generate_endpoint = f"{self.ollama_url}/api/generate"
        
        response = requests.post(
            generate_endpoint,
            json={
                'model': self.completion_model,
                'prompt': prompt,
                'stream': False,
                'options': {
                    'temperature': 0.1,  # Lower temperature for factual answers
                    'top_p': 0.9,
                }
            },
            headers=headers,
            timeout=120
        )
        response.raise_for_status()
        result = response.json()
        
        raw_answer = result['response'].strip()
        
        # Process citations with debug output enabled since this is the CLI tool
        final_answer, final_sources = process_citations(raw_answer, unique_sources, debug=self.debug)
        
        return {
            'answer': final_answer,
            'sources': final_sources,
            'num_tokens': result.get('eval_count', 0),
        }
    
    def chat(self, query: str, top_k: int = 5):
        """Process a chat query."""
        print(f"\n{'='*80}")
        print(f"QUESTION: {query}")
        print(f"{'='*80}\n")
        
        # Retrieve relevant chunks
        if self.debug:
            print("Retrieving relevant chunks...\n")
        
        retrieved = self.retrieve(query, top_k=top_k)
        
        if self.debug:
            print("TOP RETRIEVED CHUNKS:")
            print("-" * 80)
            for i, chunk in enumerate(retrieved):
                title = chunk['metadata'].get('title', 'Unknown')
                score = chunk['score']
                preview = chunk['text'][:150].replace('\n', ' ')
                print(f"{i+1}. [{score:.4f}] {title}")
                print(f"   {preview}...")
                print()
            print("-" * 80)
            print()
        
        if not retrieved:
            print("No relevant information found in the knowledge base.")
            return
        
        # Generate answer
        if self.debug:
            print("Generating answer...\n")
        
        try:
            result = self.generate_answer(query, retrieved)
            
            print("ANSWER:")
            print("-" * 80)
            print(result['answer'])
            print("-" * 80)
            print()
            
            print("SOURCES:")
            for source in result['sources']:
                title = source['title']
                url = source.get('source_url', 'N/A')
                section = source.get('section', 'N/A')
                print(f"  • {title}")
                print(f"    Section: {section}")
                print(f"    URL: {url}")
                print()
            
            if self.debug:
                print(f"Tokens used: {result['num_tokens']}")
        
        except Exception as e:
            print(f"Error generating answer: {e}")
            if self.debug:
                import traceback
                traceback.print_exc()


def main():
    parser = argparse.ArgumentParser(description="Chat with KB using RAG")
    parser.add_argument(
        "query",
        type=str,
        help="Question to ask",
    )
    parser.add_argument(
        "--index-dir",
        type=str,
        default="output/kb_index",
        help="Directory containing the index",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Number of chunks to retrieve",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Show debug information including retrieval scores",
    )
    
    args = parser.parse_args()
    
    try:
        chat = KBChat(index_dir=args.index_dir, debug=args.debug)
        chat.chat(args.query, top_k=args.top_k)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        return 1
    except Exception as e:
        print(f"Error: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
