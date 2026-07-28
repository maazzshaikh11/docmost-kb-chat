#!/usr/bin/env python3
"""
RAG Microservice for Docmost KB Chat POC.

Wraps existing FAISS + all-MiniLM-L6-v2 + Ollama Cloud pipeline.
Run with:
  venv/bin/uvicorn rag_server:app --host 0.0.0.0 --port 8765 --reload

Endpoints:
  GET  /health  →  {"status": "ok", "vectors": N, "chunks": N}
  POST /query   →  {"query": "...", "top_k": 5}
               ←  {"answer": "...", "sources": [...], "chunks_used": N, "model": "..."}
"""

import json
import os
import pickle
from contextlib import asynccontextmanager
from pathlib import Path

import faiss
import numpy as np
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sentence_transformers import SentenceTransformer

from citation_utils import process_citations

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# Resolve paths relative to this file
HERE = Path(__file__).parent
INDEX_DIR = HERE / "output" / "kb_index"
PROJECT_ROOT = HERE.parent.parent
load_dotenv(PROJECT_ROOT / ".env")

OLLAMA_URL = os.getenv("OLLAMA_API_URL", "https://ollama.com/api")
OLLAMA_KEY = os.getenv("OLLAMA_API_KEY", "")
COMPLETION_MODEL = os.getenv("AI_COMPLETION_MODEL", "gpt-oss:20b")

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
        f"model={embedding_model_name}  ollama={OLLAMA_URL}  "
        f"completion={COMPLETION_MODEL}  key={'✓' if OLLAMA_KEY else '✗ MISSING'}"
    )
    yield
    # nothing to tear down


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Docmost KB RAG Service",
    description="FAISS + sentence-transformers + Ollama Cloud",
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
    q_emb = _embed(query).reshape(1, -1)
    faiss.normalize_L2(q_emb)
    scores, indices = state.index.search(q_emb, top_k)

    results = []
    for score, idx in zip(scores[0], indices[0]):
        if idx < len(state.chunks):
            chunk = state.chunks[idx].copy()
            chunk["score"] = float(score)
            results.append(chunk)
    return results


def _generate(query: str, chunks: list[dict]) -> dict:
    """Generate answer using Ollama Cloud."""
    unique_sources = []
    source_map = {}  # mapping from (title, article_id) -> 1-based index

    for chunk in chunks:
        meta = chunk["metadata"]
        title = meta.get("title", "Unknown Article")
        article_id = meta.get("article_id")
        
        # Use article_id as primary key if available, else title
        key = article_id if article_id else title
        
        if key not in source_map:
            unique_sources.append(
                Source(
                    title=title,
                    article_id=article_id,
                    source_url=meta.get("source_url"),
                    section=meta.get("section"),
                )
            )
            source_map[key] = len(unique_sources)

    context_parts = []
    for chunk in chunks:
        meta = chunk["metadata"]
        title = meta.get("title", "Unknown Article")
        article_id = meta.get("article_id")
        key = article_id if article_id else title
        citation_num = source_map[key]
        
        text = chunk["text"]
        context_parts.append(f"[{citation_num}] {title}\n{text}\n")

    context = "\n".join(context_parts)

    prompt = f"""You are a helpful assistant for the Contacts+ Knowledge Base.

Answer the user's question using ONLY the information provided in the context below.

IMPORTANT RULES:
1. Answer ONLY from the provided context.
2. If the context does not contain enough information, say "I don't have enough information in the knowledge base to answer this question."
3. Do NOT invent or assume information.
4. Be concise and direct.
5. You MUST include inline citations immediately after each supported claim using the bracketed numbers from the context (e.g. [1], [2]).
6. Do NOT repeat the same citation consecutively. Output [1] instead of [1][1] or [1] [1].
7. Combine different citations without spaces if multiple sources support the same claim: [1][2].
8. Do NOT output a separate "Sources: [1]" list or sentence at the end of your answer. Include citations inline only.
9. You do not need to cite every provided source, only the ones you actually use.

CONTEXT:
{context}

USER QUESTION: {query}

ANSWER:"""

    headers = {"Content-Type": "application/json"}
    if OLLAMA_KEY:
        headers["Authorization"] = f"Bearer {OLLAMA_KEY}"

    # Resolve generate endpoint
    if OLLAMA_URL.rstrip("/").endswith("/api"):
        generate_url = f"{OLLAMA_URL}/generate"
    else:
        generate_url = f"{OLLAMA_URL}/api/generate"

    resp = requests.post(
        generate_url,
        json={
            "model": COMPLETION_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.1, "top_p": 0.9},
        },
        headers=headers,
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()
    
    raw_answer = data["response"].strip()
    
    # Process citations (normalize, filter unused, remap)
    final_answer, final_sources = process_citations(raw_answer, unique_sources, debug=False)

    return {
        "answer": final_answer,
        "sources": final_sources,
        "tokens": data.get("eval_count", 0),
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
        "completion_model": COMPLETION_MODEL,
        "ollama_url": OLLAMA_URL,
        "ollama_key_set": bool(OLLAMA_KEY),
    }


@app.post("/query", response_model=QueryResponse)
def query(req: QueryRequest):
    """Retrieve relevant chunks and generate a grounded answer."""
    if state.index is None:
        raise HTTPException(status_code=503, detail="Index not loaded")

    chunks = _retrieve(req.query, req.top_k)
    if not chunks:
        return QueryResponse(
            answer="I could not find any relevant information in the knowledge base.",
            sources=[],
            chunks_used=0,
            model=COMPLETION_MODEL,
        )

    try:
        result = _generate(req.query, chunks)
    except requests.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Ollama Cloud error: {exc.response.status_code} – {exc.response.text[:200]}",
        ) from exc
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Ollama Cloud unreachable: {exc}") from exc

    return QueryResponse(
        answer=result["answer"],
        sources=result["sources"],
        chunks_used=len(chunks),
        model=COMPLETION_MODEL,
    )
