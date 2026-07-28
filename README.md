# Docmost KB Chat

A Retrieval-Augmented Generation (RAG) based Knowledge Base Chat implementation for Docmost. This project enables users to ask natural language questions about imported knowledge base content and receive context-aware responses with source citations.

The project also includes a migration pipeline used to import an external knowledge base into Docmost, generate searchable indexes, and support AI-powered question answering.

---

## Features

- Knowledge base migration from an external support portal
- Automated HTML content extraction and asset preservation
- Docmost-compatible import generation
- FAISS vector indexing for semantic search
- Retrieval-Augmented Generation (RAG)
- Ollama-powered local LLM integration
- Source-aware responses with citations
- Citation links back to Docmost documents
- Chat history support
- Integrated KB Chat interface within Docmost

---

## Architecture

```
External Knowledge Base
          │
          ▼
Web Scraper  
          │
          ▼
Docmost Import
          │
          ▼
Knowledge Base Pages
          │
          ▼
FAISS Index Generation
          │
          ▼
Python RAG Service
          │
          ▼
NestJS API
          │
          ▼
Docmost KB Chat UI
```

---

## Project Structure

```
apps/
├── client/              # Docmost frontend
├── server/              # NestJS backend

scripts/
└── zendesk-poc/
    ├── full_migration.py
    ├── migrate_article.py
    ├── kb_indexer.py
    ├── rag_server.py
    ├── kb_chat.py
    ├── citation_utils.py
    └── requirements*.txt
```

---

## Technology Stack

### Backend

- NestJS
- TypeScript
- Python
- FastAPI
- FAISS
- Ollama

### Frontend

- React
- TypeScript
- Docmost

### AI

- Retrieval-Augmented Generation (RAG)
- FAISS Vector Search
- Ollama

---

## Installation

### Clone the repository

```bash
git clone https://github.com/maazzshaikh11/docmost-kb-chat.git
cd docmost-kb-chat 
```

### Install Node.js dependencies

```bash
pnpm install
```

### Install Python dependencies

```bash
cd scripts/zendesk-poc

pip install -r requirements.txt
pip install -r requirements-rag.txt
```

---

## Running the Project

### Start Docmost

```bash
pnpm dev
```

### Start the RAG service

```bash
python rag_server.py
```

## Configuration

Before starting the application, update the following values in `docker-compose.yml`:

- `APP_SECRET`
- `POSTGRES_PASSWORD`
- `DATABASE_URL` (ensure the password matches `POSTGRES_PASSWORD`)

After updating the configuration, start the services:

```bash
docker compose up -d
```

---

## Knowledge Base Migration

The migration pipeline performs the following tasks:

1. Crawl the source knowledge base
2. Download articles and associated assets
3. Preserve document structure
4. Generate Docmost-compatible content
5. Package content for import

Example:

```bash
python full_migration.py
```

---

## Index Generation

Generate the FAISS vector index after importing content into Docmost.

```bash
python kb_indexer.py
```

---

## KB Chat Flow

1. User submits a question.
2. NestJS forwards the request to the RAG service.
3. Relevant documents are retrieved using FAISS.
4. Ollama generates a response using retrieved context.
5. Citations are processed and returned.
6. The frontend displays the answer with clickable source references.

---

## Repository Contents

### Migration

- Knowledge base scraping
- HTML conversion
- Asset downloading
- Docmost import generation

### Retrieval

- FAISS index creation
- Semantic search
- Citation processing

### Application

- NestJS API
- Docmost frontend integration
- Chat interface
- Conversation history

---

## Requirements

- Node.js
- pnpm
- Python 3.10+
- Ollama
- FAISS

---

## License

This project is intended for internal development and evaluation purposes.