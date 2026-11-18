# Deployment Plan: contract-review-agent → 23.144.68.246 (k3s)

## Goal
Deploy the contract-review-agent (FastAPI backend + Next.js frontend) to the remote k3s cluster so others can access it via `23.144.68.246:<NodePort>`.

## Architecture (deployed)

```
Internet ──> 23.144.68.246:30830 (NodePort)
                │
                ▼
         ┌─────────────────────────────┐
         │  review-agent-frontend Pod   │  (Next.js standalone, port 3000)
         │  Nginx serves static + proxy │
         │  /api/* -> backend           │
         └──────────────┬──────────────┘
                        │ (ClusterIP)
                        ▼
         ┌─────────────────────────────┐
         │  review-agent-backend Pod    │  (FastAPI + LangGraph, port 8000)
         │  CopilotKit AG-UI endpoint   │
         │  /api/copilotkit -> graph    │
         └──────────────┬──────────────┘
                        │
            ┌───────────┴───────────┐
            ▼                       ▼
   postgres.postgres.svc      linjie.love relay
   (law_bench DB,             (OPENAI_API_BASE,
    agent_runs table)          models via litellm)
```

## Decisions
- **Access**: NodePort `30830` (frontend, reachable as `http://23.144.68.246:30830`). Backend is ClusterIP-only (frontend proxies `/api/*` to it). This matches the law-bench pattern (30820).
- **Frontend**: Next.js `output: "standalone"` build → served by a Node runtime in the same image (simpler than Nginx + static export, and CopilotKit needs an API route server). One container.
- **Backend**: Python image built on `uv:python3.12-bookworm-slim` (same base as law-bench Dockerfile), runs `uvicorn api.main:app`.
- **Database**: Reuse `postgres.postgres.svc.cluster.local:5432/law_bench` (same as law-bench). Add `agent_runs` table via migration on startup.
- **Secrets**: Out-of-band K8s Secret `review-agent-secrets` with `database_url`, `OPENAI_API_KEY`, `OPENAI_API_BASE`, reviewer models (matches law-bench's `law-bench-db` pattern).
- **Namespace**: `law-bench` (reuse existing ns + existing `harbor-pull` imagePullSecret).
- **ArgoCD**: NOT used for this service (avoid the selfHeal/git-push cycle). Apply manifests directly with `kubectl`. Keeps it simple and reversible.

## Files to Create

### 1. `contract-review-agent/Dockerfile.backend`
- Base: `ghcr.io/astral-sh/uv:python3.12-bookworm-slim`
- Copy `pyproject.toml uv.lock`, `uv sync --frozen --no-dev`
- Copy `agent/`, `api/`, `db/`, and the parent `src/` (needed for `src.*` imports)
- Install `libpq-dev` for psycopg
- Run migration on startup, then `uvicorn api.main:app --host 0.0.0.0 --port 8000`

### 2. `contract-review-agent/frontend/Dockerfile`
- Base: `node:20-alpine` (build) + `node:20-alpine` (run)
- `npm ci && npm run build` (standalone output)
- Run `node server.js` on port 3000
- Add `next.config.js` with `output: "standalone"`

### 3. `contract-review-agent/deploy/` (k8s manifests)
- `namespace.yaml` (reuse `law-bench` - actually skip, ns exists)
- `backend-deployment.yaml` - 1 replica, envFrom `review-agent-secrets`, port 8000
- `backend-service.yaml` - ClusterIP port 8000
- `frontend-deployment.yaml` - 1 replica, env `BACKEND_URL=http://review-agent-backend:8000`, port 3000
- `frontend-service.yaml` - NodePort 30830 → port 3000

## Build & Deploy Steps

### Step 1: Add `next.config.js` (standalone output)
Enables optimized production build.

### Step 2: Build & push backend image (on remote server)
```bash
# SSH to server, clone repo, build, push to Harbor
ssh root@23.144.68.246
cd /tmp && git clone https://github.com/law-ai-official/law-bench.git review-deploy
cd review-deploy/contract-review-agent
docker build -t 23.144.68.246:30880/law-bench/review-agent-backend:latest -f Dockerfile.backend .
docker push 23.144.68.246:30880/law-bench/review-agent-backend:latest
```

### Step 3: Build & push frontend image (on remote server)
```bash
cd /tmp/review-deploy/contract-review-agent/frontend
docker build -t 23.144.68.246:30880/law-bench/review-agent-frontend:latest .
docker push 23.144.68.246:30880/law-bench/review-agent-frontend:latest
```

### Step 4: Create secrets + apply manifests
```bash
kubectl -n law-bench create secret generic review-agent-secrets \
  --from-literal=database_url='postgresql://app:CHANGEME@postgres.postgres.svc.cluster.local:5432/law_bench' \
  --from-literal=OPENAI_API_KEY='<from .env>' \
  --from-literal=OPENAI_API_BASE='https://www.linjie.love/v1' \
  --from-literal=REVIEWER_1_MODEL='openai/kimi-k3' \
  --from-literal=REVIEWER_1_LENS='legal_accuracy' \
  --from-literal=REVIEWER_1_NAME='Legal Reviewer' \
  --from-literal=REVIEWER_2_MODEL='openai/qwen-3.7-plus' \
  --from-literal=REVIEWER_2_LENS='commercial_fairness' \
  --from-literal=REVIEWER_2_NAME='Commercial Reviewer' \
  --from-literal=REVIEWER_3_MODEL='openai/glm-5.2' \
  --from-literal=REVIEWER_3_LENS='completeness' \
  --from-literal=REVIEWER_3_NAME='Completeness Reviewer' \
  --from-literal=QUIZ_MODEL='openai/glm-5.2'

kubectl apply -f deploy/
```

### Step 5: Verify
```bash
kubectl -n law-bench get pods -l app=review-agent-backend
kubectl -n law-bench get svc review-agent-frontend
curl http://23.144.68.246:30830
curl http://23.144.68.246:30830/api/health
```

## Access URLs (after deploy)
- **Frontend UI**: `http://23.144.68.246:30830`
- **Backend API /docs**: `http://23.144.68.246:30830/api/docs` (proxied) or `http://23.144.68.246:30830/api/health`
- **CopilotKit AG-UI**: `http://23.144.68.246:30830/api/copilotkit`

## Risks / Rollback
- If pods CrashLoopBackOff: `kubectl -n law-bench logs <pod>` to debug
- Rollback: `kubectl -n law-bench delete -f deploy/` + delete secrets
- The `agent_runs` table migration is idempotent (CREATE TABLE IF NOT EXISTS)
- NodePort 30830 is currently free (verified against existing NodePorts list)

## Out of Scope
- ArgoCD management (direct kubectl apply is simpler for one-off service)
- TLS/HTTPS (NodePort plain HTTP for now; add cert-manager later if needed)
- Persistent volumes (agent_runs lives in the shared Postgres, no PVC needed)
