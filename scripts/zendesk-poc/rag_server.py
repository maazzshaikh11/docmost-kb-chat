#!/usr/bin/env python3
"""
RAG Microservice for Docmost KB Chat POC (Semantic Search Version).

Wraps existing FAISS + all-MiniLM-L6-v2 pipeline.
Run with:
  venv/bin/uvicorn rag_server:app --host 0.0.0.0 --port 8765 --reload

Endpoints:
  GET  /health  →  {"status": "ok", "vectors": N, "chunks": N}
  POST /query   →  {"query": "...", "top_k": 5}
               ←  {"answer": "...", "sources": [...], "chunks_used": N, "model": "..."}
"""

import json
import pickle
from contextlib import asynccontextmanager
from pathlib import Path

import faiss
import numpy as np
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sentence_transformers import SentenceTransformer

# ---------------------------------------------------------------------------
# Configuration Constants
# ---------------------------------------------------------------------------

# Article reranking parameters
FAISS_CANDIDATES = 15           # Number of chunks to retrieve for reranking
ARTICLE_BONUS_WEIGHT = 0.3      # Weight applied to bonus chunks in aggregate score
MAX_BONUS_CHUNKS = 2            # Maximum number of bonus chunks to consider per article

# Debug output control
DEBUG_RAG = False               # Set to True to enable detailed ranking debug output

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# Resolve paths relative to this file
HERE = Path(__file__).parent
INDEX_DIR = HERE / "output" / "kb_index"
PROJECT_ROOT = HERE.parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# ---------------------------------------------------------------------------
# Global state (loaded once at startup)
# ---------------------------------------------------------------------------

class State:
    index: faiss.Index = None
    chunks: list = None
    embedding_model: SentenceTransformer = None
    config: dict = None


state = State()


# ---------------------------------------------------------------------------
# Lifespan: load index and model once
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load RAG components at startup."""
    print(f"Loading KB index from {INDEX_DIR} ...")

    config_path = INDEX_DIR / "config.json"
    if not config_path.exists():
        raise FileNotFoundError(
            f"Index config not found at {config_path}. Run kb_indexer.py first."
        )

    with open(config_path) as f:
        state.config = json.load(f)

    embedding_model_name = state.config.get("embedding_model", "all-MiniLM-L6-v2")
    print(f"Loading embedding model: {embedding_model_name}")
    state.embedding_model = SentenceTransformer(embedding_model_name)

    print("Loading FAISS index ...")
    state.index = faiss.read_index(str(INDEX_DIR / "faiss.index"))

    print("Loading chunks ...")
    with open(INDEX_DIR / "chunks.pkl", "rb") as f:
        state.chunks = pickle.load(f)

    print(
        f"✓ Ready  vectors={state.index.ntotal}  chunks={len(state.chunks)}  "
        f"model={embedding_model_name}"
    )
    yield
    # nothing to tear down


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Docmost KB Semantic Search Service",
    description="FAISS + sentence-transformers (No Ollama)",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tightened in production
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)


class Source(BaseModel):
    title: str
    article_id: str | None = None
    source_url: str | None = None
    section: str | None = None


class QueryResponse(BaseModel):
    answer: str
    sources: list[Source]
    chunks_used: int
    model: str


# ---------------------------------------------------------------------------
# Helpers (mirrored from kb_chat.py)
# ---------------------------------------------------------------------------

def _embed(text: str) -> np.ndarray:
    """Embed text using sentence-transformers."""
    embedding = state.embedding_model.encode(text, convert_to_numpy=True)
    return embedding.astype(np.float32)


def _retrieve(query: str, top_k: int) -> list[dict]:
    """Retrieve top-k most relevant chunks via FAISS cosine similarity."""
    # Internally retrieve more candidates for article-level reranking
    # This gives us better article-level signals
    retrieval_k = max(top_k * 3, FAISS_CANDIDATES)
    
    q_emb = _embed(query).reshape(1, -1)
    faiss.normalize_L2(q_emb)
    scores, indices = state.index.search(q_emb, retrieval_k)

    results = []
    for score, idx in zip(scores[0], indices[0]):
        if idx < len(state.chunks):
            chunk = state.chunks[idx].copy()
            chunk["score"] = float(score)
            chunk["chunk_idx"] = int(idx)
            results.append(chunk)
    return results


def _rerank_by_article(chunks: list[dict]) -> list[str]:
    """
    Rerank articles based on aggregate chunk scores.
    
    Groups chunks by article and computes aggregate score:
    agg_score = best_score + ARTICLE_BONUS_WEIGHT * sum(next MAX_BONUS_CHUNKS scores)
    
    This rewards articles with multiple relevant chunks without letting
    many mediocre chunks accumulate excessive bonus.
    
    Returns: List of article keys ordered by aggregate score descending
    """
    from collections import defaultdict
    
    # Group chunks by article
    articles = defaultdict(list)
    
    for chunk in chunks:
        meta = chunk["metadata"]
        article_id = meta.get("article_id")
        source_url = meta.get("source_url")
        title = meta.get("title", "Unknown Article")
        
        # Use same deduplication key as _format_results
        key = article_id if article_id else (source_url if source_url else title)
        articles[key].append(chunk)
    
    # Compute aggregate score for each article
    article_scores = {}
    
    for key, article_chunks in articles.items():
        # Sort chunks by score descending
        sorted_chunks = sorted(article_chunks, key=lambda c: c["score"], reverse=True)
        sorted_scores = [c["score"] for c in sorted_chunks]
        
        best_score = sorted_scores[0]
        # Cap bonus to only next MAX_BONUS_CHUNKS highest-scoring chunks
        bonus_chunks = sorted_scores[1:MAX_BONUS_CHUNKS + 1]
        
        # Aggregate: best + ARTICLE_BONUS_WEIGHT * sum(next N)
        agg_score = best_score + ARTICLE_BONUS_WEIGHT * sum(bonus_chunks)
        article_scores[key] = agg_score
    
    # Return article keys sorted by aggregate score
    ranked_keys = sorted(article_scores.keys(), 
                        key=lambda k: article_scores[k], 
                        reverse=True)
    
    return ranked_keys


def _clean_text(text: str) -> str:
    """
    Clean and format text for display in the chat UI.
    
    - Fix inline numbered items (split mid-sentence numbers to new lines)
    - Strip heading markers but keep the text
    - Normalize list formatting to consistent style
    - Bold important UI terms
    - Preserve list and paragraph structure
    - Remove metadata artifacts
    - Strip leading heading if present
    """
    import re
    
    # Remove metadata artifacts that might appear inline
    text = re.sub(r'(?i)article\s+id\s*:\s*\S+', '', text)
    text = re.sub(r'(?i)source\s+url\s*:\s*\S+', '', text)
    text = re.sub(r'(?i)section\s*:\s*\S+', '', text)
    
    # FIX 1: Split inline numbered items that don't start on their own line
    # Pattern: sentence-ending punctuation + whitespace + number. + capital letter
    # Example: "...Firefox, Safari, Edge, and Opera. 2. Create your Contacts+ account"
    # Becomes: "...Firefox, Safari, Edge, and Opera.\n\n2. Create your Contacts+ account"
    text = re.sub(r'([.:])\s+(\d+)\.\s+([A-Z])', r'\1\n\n\2. \3', text)
    
    lines = text.splitlines()
    out = []
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        
        if not stripped:
            out.append('')
            continue
        
        # Remove heading markers (##, ###, etc.) but keep the text
        if stripped.startswith('#'):
            heading_text = re.sub(r'^#+\s*', '', stripped).strip()
            # Strip leading heading entirely (redundant with sources panel)
            if i == 0 or (i == 1 and not lines[0].strip()):
                continue
            stripped = heading_text
        
        # Normalize list markers: convert * to - for bullets
        list_match = re.match(r'^(\s*)(\*|\-|\d+\.)\s+(.+)$', stripped)
        if list_match:
            indent, marker, content = list_match.groups()
            if marker == '*':
                marker = '-'
            stripped = f"{indent}{marker} {content}"
        
        # Ensure blank lines around lists
        is_list = bool(re.match(r'^\s*([-*]|\d+\.)\s', stripped))
        prev_blank = (not out) or out[-1] == ''
        
        if is_list and not prev_blank:
            out.append('')
        
        out.append(stripped)
        
        # Blank line after last item in a list block
        if is_list and i + 1 < len(lines):
            next_line = lines[i + 1].strip()
            next_is_list = bool(re.match(r'^\s*([-*]|\d+\.)\s', next_line))
            if not next_is_list and next_line:
                out.append('')
    
    # Collapse multiple blank lines to at most 2
    result = re.sub(r'\n{3,}', '\n\n', '\n'.join(out))
    
    # FIX 2: Bold important UI terms (apply as final pass)
    ui_terms = [
        'My Contacts', 'Sync Sources', 'Add Sync Source', 'Google', 'Settings',
        'Contacts+', 'Google Contacts', 'Account Settings', 'Profile Settings',
        'Preferences', 'Menu', 'Dashboard', 'Home', 'Save', 'Cancel', 'Edit',
        'Delete', 'Add', 'Remove', 'Import', 'Export', 'Sync', 'Refresh',
        'Sign In', 'Sign Out', 'Log In', 'Log Out', 'Register', 'Password',
        'Email', 'Username', 'Profile', 'Account', 'Contact List', 'Groups',
        'Tags', 'Labels', 'Search', 'Filter', 'Sort', 'View', 'More Options',
        'Help', 'Support', 'FAQ', 'Documentation', 'Tutorial', 'Guide',
    ]
    
    for term in ui_terms:
        # Match whole words only, avoid double-bolding
        pattern = r'(?<!\*\*)(?<!\w)(' + re.escape(term) + r')(?!\w)(?!\*\*)'
        result = re.sub(pattern, r'**\1**', result, flags=re.IGNORECASE)
    
    # Clean up any double-bolding that might have occurred
    result = re.sub(r'\*\*\*\*+', '**', result)
    
    return result.strip()


def _format_results(chunks: list[dict], query: str = None) -> dict:
    """
    Format FAISS retrieved chunks into answer text and sources list.
    
    Strategy:
    1. Rerank by article (aggregate scores across chunks)
    2. Return highest-ranked article's best chunk as main answer
    3. Only merge an adjacent chunk if:
       - It's also in the top-k retrieved results (independently retrieved), OR
       - Its similarity to the query is within 0.05 of the top chunk's score
    4. Next 2 unique articles go in sources only (not concatenated to answer)
    5. Do not merge unrelated chunks or chunks from different articles
    """
    if not chunks:
        return {"answer": "", "sources": [], "tokens": 0}
    
    # Rerank articles by aggregate score
    ranked_article_keys = _rerank_by_article(chunks)
    
    # Group chunks by article for easy lookup
    from collections import defaultdict
    articles = defaultdict(list)
    
    for chunk in chunks:
        meta = chunk["metadata"]
        article_id = meta.get("article_id")
        source_url = meta.get("source_url")
        title = meta.get("title", "Unknown Article")
        key = article_id if article_id else (source_url if source_url else title)
        articles[key].append(chunk)
    
    # Sort chunks within each article by score
    for key in articles:
        articles[key] = sorted(articles[key], key=lambda c: c.get("score", 0), reverse=True)
    
    # Get the top-ranked article's best chunk
    if not ranked_article_keys:
        return {"answer": "", "sources": [], "tokens": 0}
    
    top_article_key = ranked_article_keys[0]
    top_chunk = articles[top_article_key][0]  # Best chunk from top article
    top_score = top_chunk.get("score", 0)
    top_idx = top_chunk.get("chunk_idx")
    
    # Collect chunk indices that are in the retrieved results
    retrieved_indices = {c.get("chunk_idx") for c in chunks if c.get("chunk_idx") is not None}
    
    # Check if we should include adjacent chunks
    answer_chunks = [top_chunk]
    
    if top_idx is not None:
        # Check preceding chunk
        if top_idx - 1 >= 0:
            prev_chunk = state.chunks[top_idx - 1]
            prev_meta = prev_chunk["metadata"]
            prev_article_id = prev_meta.get("article_id")
            prev_source_url = prev_meta.get("source_url")
            prev_title = prev_meta.get("title", "Unknown Article")
            prev_key = prev_article_id if prev_article_id else (prev_source_url if prev_source_url else prev_title)
            
            # Only include if same article AND (independently retrieved OR high similarity)
            if prev_key == top_article_key:
                should_include = False
                
                # Check if independently retrieved
                if (top_idx - 1) in retrieved_indices:
                    should_include = True
                # Check similarity threshold (within 0.05 of top score)
                elif query:
                    prev_embedding = _embed(prev_chunk["text"]).reshape(1, -1)
                    faiss.normalize_L2(prev_embedding)
                    query_embedding = _embed(query).reshape(1, -1)
                    faiss.normalize_L2(query_embedding)
                    prev_score = float(np.dot(prev_embedding, query_embedding.T)[0, 0])
                    if abs(prev_score - top_score) <= 0.05:
                        should_include = True
                
                if should_include:
                    answer_chunks.insert(0, prev_chunk)
        
        # Check following chunk
        if top_idx + 1 < len(state.chunks):
            next_chunk = state.chunks[top_idx + 1]
            next_meta = next_chunk["metadata"]
            next_article_id = next_meta.get("article_id")
            next_source_url = next_meta.get("source_url")
            next_title = next_meta.get("title", "Unknown Article")
            next_key = next_article_id if next_article_id else (next_source_url if next_source_url else next_title)
            
            # Only include if same article AND (independently retrieved OR high similarity)
            if next_key == top_article_key:
                should_include = False
                
                # Check if independently retrieved
                if (top_idx + 1) in retrieved_indices:
                    should_include = True
                # Check similarity threshold (within 0.05 of top score)
                elif query:
                    next_embedding = _embed(next_chunk["text"]).reshape(1, -1)
                    faiss.normalize_L2(next_embedding)
                    query_embedding = _embed(query).reshape(1, -1)
                    faiss.normalize_L2(query_embedding)
                    next_score = float(np.dot(next_embedding, query_embedding.T)[0, 0])
                    if abs(next_score - top_score) <= 0.05:
                        should_include = True
                
                if should_include:
                    answer_chunks.append(next_chunk)
    
    # Merge answer chunks (remove overlap between adjacent chunks)
    merged_text = answer_chunks[0]["text"].strip()
    for i in range(1, len(answer_chunks)):
        curr_text = answer_chunks[i]["text"].strip()
        
        # Try to detect overlap at the boundary
        overlap_len = 0
        max_overlap = min(400, len(merged_text), len(curr_text))
        for size in range(max_overlap, 20, -1):
            if merged_text.endswith(curr_text[:size]):
                overlap_len = size
                break
        
        if overlap_len > 0:
            merged_text += curr_text[overlap_len:]
        else:
            merged_text += "\n\n" + curr_text
    
    # Clean the answer text
    answer_text = _clean_text(merged_text)
    
    # Build sources list: top 3 articles from reranked list
    sources = []
    source_map = {}
    
    for key in ranked_article_keys[:3]:
        if key in articles:
            chunk = articles[key][0]  # Get representative chunk for metadata
            meta = chunk["metadata"]
            title = meta.get("title", "Unknown Article")
            article_id = meta.get("article_id")
            source_url = meta.get("source_url")
            section = meta.get("section")
            
            sources.append(
                Source(
                    title=title,
                    article_id=article_id,
                    source_url=source_url,
                    section=section,
                )
            )
            source_map[key] = len(sources)
    
    # Add citation for the top article only
    if top_article_key in source_map:
        citation_num = source_map[top_article_key]
        answer_text += f"\n\n[{citation_num}]"
    
    return {
        "answer": answer_text,
        "sources": sources,
        "tokens": 0,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    if state.index is None:
        raise HTTPException(status_code=503, detail="Index not loaded")
    return {
        "status": "ok",
        "vectors": state.index.ntotal,
        "chunks": len(state.chunks),
        "embedding_model": state.config.get("embedding_model"),
    }


@app.post("/query", response_model=QueryResponse)
def query(req: QueryRequest):
    """Retrieve relevant chunks and format as semantic search results."""
    if state.index is None:
        raise HTTPException(status_code=503, detail="Index not loaded")

    chunks = _retrieve(req.query, req.top_k)
    if not chunks:
        return QueryResponse(
            answer="I could not find any relevant information in the knowledge base.",
            sources=[],
            chunks_used=0,
            model="semantic-search",
        )

    # DEBUG: Print rankings if enabled
    if DEBUG_RAG:
        from collections import defaultdict
        
        print("\n" + "="*80)
        print(f"QUERY: {req.query}")
        print("="*80)
        print("\nRaw FAISS ranking:")
        for i, r in enumerate(chunks[:10]):
            print(f"{i+1}. {r['metadata'].get('title', 'Unknown')[:50]:50s}  score={r['score']:.4f}")
        
        # Compute article scores for debug output
        articles = defaultdict(list)
        for chunk in chunks:
            meta = chunk["metadata"]
            article_id = meta.get("article_id")
            source_url = meta.get("source_url")
            title = meta.get("title", "Unknown Article")
            key = article_id if article_id else (source_url if source_url else title)
            articles[key].append(chunk)
        
        article_scores = {}
        for key, article_chunks in articles.items():
            sorted_chunks = sorted(article_chunks, key=lambda c: c["score"], reverse=True)
            sorted_scores = [c["score"] for c in sorted_chunks]
            best_score = sorted_scores[0]
            bonus_chunks = sorted_scores[1:MAX_BONUS_CHUNKS + 1]
            agg_score = best_score + ARTICLE_BONUS_WEIGHT * sum(bonus_chunks)
            article_scores[key] = {
                'score': agg_score,
                'title': sorted_chunks[0]['metadata'].get('title', 'Unknown'),
                'num_chunks': len(article_chunks),
                'best': best_score,
                'bonus': bonus_chunks,
                'all_scores': sorted_scores[:5]
            }
        
        print("\nArticle reranking:")
        ranked = sorted(article_scores.items(), key=lambda x: x[1]['score'], reverse=True)
        for i, (key, info) in enumerate(ranked[:10]):
            bonus_str = f"[{', '.join(f'{s:.3f}' for s in info['bonus'])}]" if info['bonus'] else "[]"
            print(f"{i+1}. {info['title'][:45]:45s}  agg={info['score']:.4f}")
            print(f"   best={info['best']:.4f} + {ARTICLE_BONUS_WEIGHT}*{bonus_str} | {info['num_chunks']} chunks | top5={[f'{s:.3f}' for s in info['all_scores']]}")
        print("="*80 + "\n")

    result = _format_results(chunks, query=req.query)

    return QueryResponse(
        answer=result["answer"],
        sources=result["sources"],
        chunks_used=len(chunks),
        model="semantic-search",
    )