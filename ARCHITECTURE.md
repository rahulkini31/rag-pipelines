# Docling Ingestion & Retrieval Architecture

This document describes the architecture for the Docling-based ingestion pipeline.

## Pipeline Overview
The system follows a linear transformation path from raw binary files to a hybrid vector store, with an optional canonical storage detour for lossless recovery.

### 1. Ingestion & Deduplication (**Hash Gate**)
- **Component**: SHA-256 Hash Gate
- **Process**: Computes a file hash upon upload.
- **Goal**: Skip unchanged documents and manage modified files via tombstone deletions.
- **Output**: Verified Binary Stream.

### 2. Layout & Structure Extraction (**Docling Extraction**)
- **Component**: `Docling DocumentConverter`
- **Process**: Performs layout analysis, reading-order resolution, OCR, and accurate table reconstruction using `TableFormer`.
- **Output**: `DoclingDocument` Object.

### 3. Canonical Artifact Storage (**DocLang Store**)
- **Component**: `DocLang Serializer`
- **Process**: Saves a lossless, AI-native representation of the document to object storage (e.g., S3/MinIO).
- **Goal**: Ensures raw PDFs never need to be re-parsed.
- **Output**: `.dclx` Archive / `.dclg.xml`.

### 4. Structure-Aware Chunking (**Hybrid Chunking**)
- **Component**: `Docling HybridChunker`
- **Process**: Splits documents based on hierarchy and token limits. It prepends section headings to chunks for better context and attaches bounding-box provenance.
- **Output**: Contextualized LangChain Documents.

### 5. Hybrid Vector Storage (**Qdrant Store**)
- **Component**: `Qdrant` + `LangChain VectorStore`
- **Process**: Upserts deterministic UUID points.
- **Index Type**: Hybrid index consisting of:
    - **Dense Vectors**: For semantic search.
    - **Sparse Vectors**: BM25 vectors via `FastEmbed` for keyword search.
    - **Metadata**: DocLang URI pointers for source attribution.
- **Output**: Hybrid Searchable Index.
