# Hybrid RAG Document Management System — Product Requirements Document

## 1. Product Overview

A web-based document management and operations cockpit for the existing Hybrid RAG pipeline. It provides an OS-like file manager for documents stored in the vector database, live telemetry visualization, ad-hoc retrieval/generation evaluations, and runtime configuration management.

## 2. Architecture Decisions

| Area | Decision |
|------|----------|
| **Frontend** | Next.js 15 App Router, TypeScript, Tailwind CSS, shadcn/ui |
| **Backend** | Existing Python pipeline + new FastAPI API layer |
| **Frontend → External Services** | Always through FastAPI; no direct AWS/Qdrant calls from browser |
| **Deployment** | **Option A**: App runs locally; remote services are AWS (Cognito, S3, DynamoDB, Secrets Manager), Qdrant Cloud |
| **Auth** | AWS Cognito, single user pool, `tenant_id` as custom user attribute |
| **Tenants** | Multi-tenant; documents shareable across tenants with owner consent |
| **Config Store** | AWS Secrets Manager, **one secret per credential** |
| **Credential Exposure** | Masked by default; reveal on demand |
| **Config Reload** | FastAPI reads config per-request with short TTL; no process restart |
| **Document View** | Flat paginated list |
| **Operations** | Upload, bulk upload, delete, bulk delete, rename, version history |
| **Preview** | Original PDF viewer + Docling-rendered Markdown/HTML + chunk count |
| **File Types** | PDF only (MVP) |
| **Telemetry** | Custom dashboard + embedded Phoenix UI |
| **Evaluations** | Ad-hoc; benchmark comparison charts |
| **Scale** | Hundreds of documents, single concurrent user |
| **Live Updates** | Server-Sent Events (SSE) |

## 3. Users & Roles

| Role | Capabilities |
|------|--------------|
| **Owner** | Full CRUD on own documents; share/revoke; run evals; manage config |
| **Recipient (shared)** | Read-only access to shared documents; can preview |

## 4. Functional Requirements

### FR-001 Authentication
- Users sign in via Cognito hosted UI or embedded flow.
- FastAPI validates JWT access tokens on every protected request.
- `tenant_id` is extracted from the Cognito custom attribute `custom:tenant_id`.
- Only users with the same `tenant_id` can access non-shared documents by default.

### FR-002 Document List
- Show a flat paginated list of documents accessible to the user's tenant.
- Columns: filename, owner, status, version, chunk count, upload date, shared badge.
- Filter by filename, status, owner.
- Auto-refresh status via SSE during processing.

### FR-003 Document Upload
- Single and bulk PDF upload.
- SHA-256 deduplication via the existing hash gate.
- Upload progress indicator.
- Triggers the existing `ProductionDocumentSystem.upload_document()` pipeline.
- Document owner = current user's tenant.

### FR-004 Document Operations
- Delete document (cascades S3 artifacts, Qdrant points, DynamoDB ledger).
- Bulk delete with confirmation.
- Rename document (updates ledger metadata; S3 key based on `doc_id` stays stable).
- View version history from DynamoDB ledger.

### FR-005 Document Preview
- Original PDF viewer via time-limited S3 presigned URL.
- Rendered Markdown/HTML extracted by Docling.
- Chunk count and per-chunk metadata panel.

### FR-006 Cross-Tenant Sharing
- Owner can share a document with another tenant (read-only).
- Shared documents appear in the recipient's document list with a "shared" badge.
- Owner can revoke sharing at any time.
- Recipients cannot delete, rename, or re-share the document.

### FR-007 Telemetry Dashboard
- Custom summary: total docs, success/failure counts, average stage duration.
- Trace list by document, stage, tenant.
- Embedded Phoenix UI via iframe for deep-dive trace inspection.

### FR-008 Evaluation Dashboard
- Trigger Ranx benchmark on selected testset.
- Trigger Ragas synthetic testset generation with progress tracking.
- Trigger TruLens RAG evaluation.
- Compare results in charts/tables (e.g., hybrid vs hybrid + reranker).

### FR-009 Configuration Management
- Fetch current config from Secrets Manager.
- Mask sensitive values; reveal on demand.
- Validate/test each service connection on save.
- Save updates Secrets Manager; changes take effect on next request via TTL refresh.

## 5. Data Model

### 5.1 DynamoDB Document Ledger
Extends the existing `ProductionDocumentSystem` ledger table.

- Partition key: `tenant_id`
- Sort key: `doc_id`
- Attributes:
  - `filename` (string)
  - `current_version` (number)
  - `sha256_hash` (string)
  - `status` (string: PROCESSING | ACTIVE | FAILED)
  - `s3_doclang_uri` (string)
  - `chunk_count` (number)
  - `updated_at` (string, ISO-8601)
  - `owner_tenant_id` (string)

### 5.2 DynamoDB Table: `DocumentShares`
New table for cross-tenant read-only sharing.

- Partition key: `shared_doc_id`
- Sort key: `recipient_tenant_id`
- Attributes:
  - `owner_tenant_id` (string)
  - `shared_at` (string, ISO-8601)
  - `revoked_at` (string | null)

### 5.3 AWS Secrets Manager Layout
One secret per credential. The application uses these names by default in the `hybridrag/dev/` namespace.

| Secret Name | Value |
|-------------|-------|
| `hybridrag/dev/qdrant/url` | Qdrant Cloud URL |
| `hybridrag/dev/qdrant/api_key` | Qdrant API key |
| `hybridrag/dev/aws/profile` | AWS profile name |
| `hybridrag/dev/aws/region` | AWS region |
| `hybridrag/dev/aws/s3_bucket` | S3 bucket name |
| `hybridrag/dev/aws/dynamodb_table` | DynamoDB ledger table name |
| `hybridrag/dev/featherless/api_key` | Featherless API key |
| `hybridrag/dev/featherless/base_url` | Featherless base URL |
| `hybridrag/dev/featherless/model` | LLM model ID |
| `hybridrag/dev/embedding/model` | Embedding model ID |
| `hybridrag/dev/judge/model` | Judge LLM model ID |
| `hybridrag/dev/cognito/user_pool_id` | Cognito User Pool ID |
| `hybridrag/dev/cognito/client_id` | Cognito App Client ID |
| `hybridrag/dev/cognito/region` | Cognito region |

**Bootstrap note**: FastAPI needs initial AWS credentials (via `AWS_PROFILE` environment variable or local `~/.aws/credentials`) to read Secrets Manager. This is the only local environment dependency.

## 6. API Contract (FastAPI)

### Auth
- `POST /auth/verify` — Validate Cognito JWT, return `tenant_id`.

### Documents
- `GET /documents?page={page}&limit={limit}&status={status}&search={search}` — List accessible documents.
- `POST /documents/upload` — Upload single/bulk PDFs (multipart/form-data).
- `DELETE /documents/{doc_id}` — Delete a document.
- `POST /documents/bulk-delete` — Bulk delete. Body: `{ "doc_ids": [...] }`.
- `PATCH /documents/{doc_id}/rename` — Rename a document. Body: `{ "new_filename": "..." }`.
- `GET /documents/{doc_id}` — Get details + presigned PDF URL.
- `GET /documents/{doc_id}/preview` — Get Docling Markdown + chunks.
- `GET /documents/{doc_id}/versions` — Get version history.

### Sharing
- `POST /documents/{doc_id}/share` — Share with a tenant. Body: `{ "recipient_tenant_id": "..." }`.
- `DELETE /documents/{doc_id}/share/{recipient_tenant_id}` — Revoke sharing.
- `GET /documents/{doc_id}/shares` — List active shares.

### Telemetry
- `GET /telemetry/summary` — Aggregated stats.
- `GET /telemetry/traces?doc_id={doc_id}&tenant_id={tenant_id}&limit={limit}` — Trace list.
- `GET /events` — SSE stream for live status updates.

### Evaluations
- `POST /evals/ranx` — Run Ranx benchmark. Body depends on testset.
- `POST /evals/ragas` — Run Ragas synthetic testset generation.
- `POST /evals/trulens` — Run TruLens RAG evaluation.
- `GET /evals/results` — Historical results.

### Config
- `GET /config` — Get current config (masked values).
- `PUT /config` — Update Secrets Manager values.
- `POST /config/validate` — Test connections with provided config.

## 7. Security Measures

| Layer | Measure |
|-------|---------|
| **Auth** | Cognito JWT validation on every request |
| **Tenant Isolation** | Every DB/Qdrant call filtered by `tenant_id` |
| **Sharing Enforcement** | Backend verifies ownership before share/revoke; recipients get read-only access |
| **External Calls** | Frontend never calls AWS/Qdrant directly |
| **S3 Access** | Time-limited presigned URLs for PDF preview |
| **Input Validation** | Pydantic schemas on all endpoints |
| **CORS** | Restrict to Next.js dev/prod origin |
| **Rate Limiting** | Basic rate limiting on upload/eval endpoints |
| **Credential Masking** | Config endpoint returns masked values unless explicitly revealed |

## 8. UI/UX Pages

| Page | Purpose |
|------|---------|
| `/login` | Cognito sign-in |
| `/documents` | File manager (list, upload, bulk ops, rename, delete) |
| `/documents/{id}` | Document detail + preview (PDF + Markdown + chunks) |
| `/telemetry` | Summary cards + trace list + embedded Phoenix iframe |
| `/evaluations` | Ad-hoc eval triggers + benchmark comparison charts |
| `/settings` | Config editor with validation and reveal toggles |

## 9. Implementation Phases

| Phase | Focus |
|-------|-------|
| **P1. Foundation** | FastAPI skeleton, Next.js setup, Cognito auth, Secrets Manager config loader, `/config` endpoints |
| **P2. Document Manager** | Document list API/UI, upload/delete/rename, SSE live updates, preview panel |
| **P3. Sharing** | `DocumentShares` table, share/revoke APIs, shared badge in UI |
| **P4. Telemetry** | Phoenix embedded iframe, custom summary/trace dashboard |
| **P5. Evaluations** | Ranx/Ragas/TruLens API wrappers, evaluation UI, comparison charts |
| **P6. Polish** | Error handling, loading states, responsive design, security review |

## 10. Risks & Notes

1. **AWS Secrets Manager bootstrap**: The local FastAPI process needs valid AWS credentials to read all other secrets. This bootstrap profile is configured via `AWS_PROFILE` or local `~/.aws/credentials`.
2. **Phoenix on local deployment**: Phoenix runs embedded in the local backend. If we later move the backend to ECS, Phoenix hosting must be revisited.
3. **Cognito custom attribute**: Initial user creation/admin tooling must assign `custom:tenant_id` to each user.
4. **Scope boundary**: PDF is the only supported file type for the MVP. DOCX/PPTX support is out of scope except where Docling already supports them.
