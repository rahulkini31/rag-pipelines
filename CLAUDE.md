# Hybrid RAG System

A platform for users to ingest their own documents and query them using a Hybrid Retrieval-Augmented Generation (RAG) approach.

## Project Goal

Build a robust system that allows users to upload diverse document types, process them into a searchable format, retrieve highly relevant context, and manage documents through a web-based interface.

## Current Progress

- **PDF Extraction**: Implemented using `docling` with OCR and accurate table structure extraction.
- **Chunking Strategy**: Qwen3-aware structure-preserving chunking using `HybridChunker`, contextual headings, and provenance metadata.
- **Vector Database**: `Qdrant` configured with dense semantic vectors, sparse BM25 vectors, and hybrid RRF retrieval.
- **Embeddings**: Featherless-hosted `Qwen/Qwen3-Embedding-8B` with query instruction formatting.
- **Reranking**: Local `Qwen/Qwen3-Reranker-0.6B` CrossEncoder on Apple Silicon MPS.
- **Telemetry**: Arize Phoenix tracing for ingestion pipeline stages.
- **Retrieval Benchmarking**: `ranx` comparison of sparse, dense, and hybrid retrieval.
- **Evaluations**: Ragas synthetic testset generation and TruLens RAG feedback evaluation.
- **PRD**: Document management system PRD finalized in `PRD.md`.
- **User Interface**: In progress — Next.js + FastAPI management cockpit.

## Pending Tasks

- [x] **FastAPI Backend**: Auth, config, document, telemetry, and evaluation endpoints (Phase 1 MVP).
- [x] **Next.js Frontend**: File manager, preview, telemetry dashboard, evaluation panel, settings (Phase 1 MVP).
- [x] **AWS Cognito**: JWT validation middleware implemented; user pool config via Secrets Manager.
- [x] **Secrets Manager**: Runtime configuration loaded from AWS Secrets Manager; local `.env` file removed.
- [x] **Cross-Tenant Sharing**: Document-level read-only sharing wired to `rag_document_shares` DynamoDB table.
- [x] **SSE Live Updates**: Real-time document status updates published from upload pipeline.
- [x] **Evaluations**: Ranx/Ragas/TruLens endpoints wired to existing modules; results persisted to S3 `evaluations/` prefix.
- [x] **Evaluations UI**: One-click run buttons with on-page results and S3-backed run history with detail view.
- [x] **Corpus-wide evals**: Evals auto-derive queries from the latest Ragas testset or fall back to corpus chunks.
- [ ] **Deployment**: Target AWS Free Tier services (app local, managed services remote) — deferred.

## Tech Stack

- **Extraction**: Docling
- **Database**: Qdrant (cloud/local)
- **Language**: Python (backend), TypeScript (frontend)
- **Backend Framework**: FastAPI
- **Frontend Framework**: Next.js 15 (App Router), Tailwind CSS, shadcn/ui
- **Auth**: AWS Cognito
- **Object Storage**: Amazon S3
- **Ledger**: Amazon DynamoDB
- **Configuration**: AWS Secrets Manager
- **Telemetry**: Arize Phoenix
