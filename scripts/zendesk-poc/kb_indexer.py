#!/usr/bin/env python3
"""
Knowledge Base Indexer for RAG.

Ingests scraped HTML articles, chunks them, generates embeddings,
and builds a searchable index.
"""

import json
import os
import pickle
import re
from pathlib import Path
from typing import Any

import faiss
import numpy as np
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer


class KBIndexer:
    """Index knowledge base articles for semantic search."""
    
    def __init__(self, articles_dir: str, index_dir: str = "output/kb_index"):
        self.articles_dir = Path(articles_dir)
        self.index_dir = Path(index_dir)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        
        # Load environment variables from project root .env
        project_root = Path(__file__).parent.parent.parent
        dotenv_path = project_root / ".env"
        load_dotenv(dotenv_path)
        
        # Use local sentence-transformers for embeddings
        print("Loading sentence-transformers model...")
        self.embedding_model_name = 'all-MiniLM-L6-v2'
        self.embedding_model = SentenceTransformer(self.embedding_model_name)
        print(f"✓ Loaded {self.embedding_model_name}")
        
        # Ollama Cloud for completion only (not used during indexing)
        self.ollama_url = os.getenv('OLLAMA_API_URL', 'https://ollama.com/api')
        self.ollama_key = os.getenv('OLLAMA_API_KEY')
        
        self.chunks = []
        self.embeddings = None
        self.index = None
    
    def extract_text_from_html(self, html_path: Path) -> dict:
        """Extract clean text and metadata from HTML article."""
        content = html_path.read_text(encoding='utf-8')
        soup = BeautifulSoup(content, 'html.parser')
        
        # Extract metadata from HTML comments
        metadata = {
            'title': None,
            'article_id': None,
            'source_url': None,
            'section': None,
        }
        
        # Check title tag
        title_tag = soup.find('title')
        if title_tag:
            metadata['title'] = title_tag.get_text(strip=True)
        
        # Extract from HTML comments
        for comment in soup.find_all(string=lambda text: isinstance(text, str) and 'Article ID:' in text):
            for line in str(comment).split('\n'):
                line = line.strip()
                if line.startswith('Article ID:'):
                    metadata['article_id'] = line.split(':', 1)[1].strip()
                elif line.startswith('Source URL:'):
                    metadata['source_url'] = line.split(':', 1)[1].strip()
                elif line.startswith('Section:'):
                    metadata['section'] = line.split(':', 1)[1].strip()
        
        # Extract body text
        body = soup.find('body')
        if not body:
            return {'metadata': metadata, 'text': '', 'headings': []}
        
        # Extract text with structure
        text_parts = []
        headings = []
        
        for element in body.descendants:
            if element.name in ['h1', 'h2', 'h3', 'h4']:
                heading_text = element.get_text(strip=True)
                if heading_text:
                    headings.append(heading_text)
                    text_parts.append(f"\n\n## {heading_text}\n")
            elif element.name == 'p':
                para_text = element.get_text(strip=True)
                if para_text:
                    text_parts.append(para_text + "\n")
            elif element.name in ['li']:
                li_text = element.get_text(strip=True)
                if li_text:
                    text_parts.append(f"- {li_text}\n")
        
        full_text = ''.join(text_parts).strip()
        
        # Clean up extra whitespace
        full_text = re.sub(r'\n{3,}', '\n\n', full_text)
        
        return {
            'metadata': metadata,
            'text': full_text,
            'headings': headings,
        }
    
    def chunk_text(self, text: str, metadata: dict, chunk_size: int = 500, overlap: int = 100) -> list[dict]:
        """
        Chunk text into overlapping segments.
        Try to break on paragraph/heading boundaries.
        """
        if not text:
            return []
        
        chunks = []
        
        # Split on double newlines (paragraphs/sections)
        sections = re.split(r'\n\n+', text)
        
        current_chunk = []
        current_length = 0
        
        for section in sections:
            section = section.strip()
            if not section:
                continue
            
            section_length = len(section)
            
            # If this section alone exceeds chunk size, split it
            if section_length > chunk_size:
                # Save current chunk if any
                if current_chunk:
                    chunk_text = '\n\n'.join(current_chunk)
                    chunks.append({
                        'text': chunk_text,
                        'metadata': metadata.copy(),
                        'char_count': len(chunk_text),
                    })
                    current_chunk = []
                    current_length = 0
                
                # Split long section by sentences
                sentences = re.split(r'(?<=[.!?])\s+', section)
                temp_chunk = []
                temp_length = 0
                
                for sentence in sentences:
                    if temp_length + len(sentence) > chunk_size and temp_chunk:
                        chunk_text = ' '.join(temp_chunk)
                        chunks.append({
                            'text': chunk_text,
                            'metadata': metadata.copy(),
                            'char_count': len(chunk_text),
                        })
                        # Keep overlap
                        temp_chunk = temp_chunk[-2:] if len(temp_chunk) >= 2 else []
                        temp_length = sum(len(s) for s in temp_chunk)
                    
                    temp_chunk.append(sentence)
                    temp_length += len(sentence)
                
                if temp_chunk:
                    chunk_text = ' '.join(temp_chunk)
                    chunks.append({
                        'text': chunk_text,
                        'metadata': metadata.copy(),
                        'char_count': len(chunk_text),
                    })
            
            # Normal case: add section to current chunk
            elif current_length + section_length > chunk_size and current_chunk:
                # Save current chunk
                chunk_text = '\n\n'.join(current_chunk)
                chunks.append({
                    'text': chunk_text,
                    'metadata': metadata.copy(),
                    'char_count': len(chunk_text),
                })
                
                # Start new chunk with overlap
                if overlap > 0 and current_chunk:
                    # Keep last section for overlap
                    current_chunk = [current_chunk[-1], section]
                    current_length = len(current_chunk[-2]) + section_length
                else:
                    current_chunk = [section]
                    current_length = section_length
            else:
                current_chunk.append(section)
                current_length += section_length
        
        # Add remaining chunk
        if current_chunk:
            chunk_text = '\n\n'.join(current_chunk)
            chunks.append({
                'text': chunk_text,
                'metadata': metadata.copy(),
                'char_count': len(chunk_text),
            })
        
        return chunks
    
    def generate_embedding(self, text: str) -> np.ndarray:
        """Generate embedding using sentence-transformers."""
        embedding = self.embedding_model.encode(text, convert_to_numpy=True)
        return embedding.astype(np.float32)
    
    def ingest_articles(self):
        """Ingest all HTML articles from the scraped KB."""
        print(f"\n{'='*80}")
        print("INGESTING ARTICLES")
        print(f"{'='*80}\n")
        
        html_files = list(self.articles_dir.rglob("*.html"))
        print(f"Found {len(html_files)} HTML files")
        
        article_count = 0
        total_chunks = 0
        
        for html_file in html_files:
            try:
                # Extract text and metadata
                article_data = self.extract_text_from_html(html_file)
                
                if not article_data['text']:
                    print(f"  Skipping {html_file.name} (no text)")
                    continue
                
                # Chunk the article
                chunks = self.chunk_text(
                    article_data['text'],
                    article_data['metadata'],
                    chunk_size=500,
                    overlap=100
                )
                
                if chunks:
                    self.chunks.extend(chunks)
                    article_count += 1
                    total_chunks += len(chunks)
                    
                    title = article_data['metadata'].get('title', html_file.name)
                    print(f"  {title[:60]}: {len(chunks)} chunks")
            
            except Exception as e:
                print(f"  Error processing {html_file.name}: {e}")
        
        print(f"\n{'='*80}")
        print(f"Ingested {article_count} articles into {total_chunks} chunks")
        print(f"{'='*80}\n")
    
    def build_index(self):
        """Generate embeddings and build FAISS index."""
        if not self.chunks:
            print("No chunks to index!")
            return
        
        print(f"\n{'='*80}")
        print("GENERATING EMBEDDINGS")
        print(f"{'='*80}\n")
        
        embeddings_list = []
        
        for i, chunk in enumerate(self.chunks):
            try:
                embedding = self.generate_embedding(chunk['text'])
                embeddings_list.append(embedding)
                
                if (i + 1) % 10 == 0:
                    print(f"  Generated {i + 1}/{len(self.chunks)} embeddings...")
            
            except Exception as e:
                print(f"  Error generating embedding for chunk {i}: {e}")
                # Use zero vector as fallback
                embeddings_list.append(np.zeros(768, dtype=np.float32))
        
        self.embeddings = np.vstack(embeddings_list)
        
        print(f"\n{'='*80}")
        print("BUILDING FAISS INDEX")
        print(f"{'='*80}\n")
        
        # Normalize embeddings for cosine similarity
        faiss.normalize_L2(self.embeddings)
        
        # Build FAISS index (inner product = cosine similarity for normalized vectors)
        dimension = self.embeddings.shape[1]
        self.index = faiss.IndexFlatIP(dimension)
        self.index.add(self.embeddings)
        
        print(f"Index built with {self.index.ntotal} vectors")
        print(f"Embedding dimension: {dimension}")
    
    def save_index(self):
        """Save index and chunks to disk."""
        print(f"\n{'='*80}")
        print("SAVING INDEX")
        print(f"{'='*80}\n")
        
        # Save FAISS index
        index_path = self.index_dir / "faiss.index"
        faiss.write_index(self.index, str(index_path))
        print(f"Saved FAISS index: {index_path}")
        
        # Save chunks metadata
        chunks_path = self.index_dir / "chunks.pkl"
        with open(chunks_path, 'wb') as f:
            pickle.dump(self.chunks, f)
        print(f"Saved chunks: {chunks_path}")
        
        # Save config
        config = {
            'embedding_model': self.embedding_model_name,
            'embedding_type': 'sentence-transformers',
            'ollama_url': self.ollama_url,
            'num_articles': len(set(c['metadata'].get('article_id') for c in self.chunks if c['metadata'].get('article_id'))),
            'num_chunks': len(self.chunks),
            'embedding_dimension': self.embeddings.shape[1],
        }
        config_path = self.index_dir / "config.json"
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)
        print(f"Saved config: {config_path}")
        
        print(f"\n{'='*80}\n")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Index KB articles for RAG")
    parser.add_argument(
        "--articles-dir",
        type=str,
        default="output/full_migration",
        help="Directory containing scraped HTML articles",
    )
    parser.add_argument(
        "--index-dir",
        type=str,
        default="output/kb_index",
        help="Directory to save the index",
    )
    
    args = parser.parse_args()
    
    print(f"\n{'='*80}")
    print("KB INDEXER - Using local sentence-transformers for embeddings")
    print(f"{'='*80}\n")
    
    indexer = KBIndexer(args.articles_dir, args.index_dir)
    indexer.ingest_articles()
    indexer.build_index()
    indexer.save_index()
    
    print("✓ Indexing complete!")
    return 0


if __name__ == "__main__":
    exit(main())
