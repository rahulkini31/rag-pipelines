# Hybrid RAG Frontend

Next.js 15 application for managing documents, telemetry, evaluations, and configuration.

## Development

Install dependencies:

```bash
cd frontend
npm install
```

Create `.env.local` with only the backend URL (no secrets):

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

All sensitive configuration lives in AWS Secrets Manager under `hybridrag/dev/*`.
The FastAPI backend reads those secrets; the browser never accesses them directly.

Start the dev server:

```bash
npm run dev
```

The app runs at http://localhost:3000.

## Authentication

For local development, start the FastAPI backend with auth bypass:

```bash
cd ..
source .venv/bin/activate
export AWS_PROFILE=rag-local-role
export AWS_DEFAULT_REGION=us-east-1
export COGNITO_BYPASS_USER_ID=local-user
export COGNITO_BYPASS_TENANT_ID=local-tenant
uvicorn api.main:app --reload
```

Use any value in the **Access Token** field on the login page.

For production, configure the Cognito secrets in AWS Secrets Manager
(`hybridrag/dev/cognito/*`) and remove the bypass environment variables.
