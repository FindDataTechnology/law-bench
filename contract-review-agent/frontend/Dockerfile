# syntax=docker/dockerfile:1
#
# contract-review-agent frontend image (Next.js standalone).
# Serves the CopilotKit chat + state panel on port 3000. Proxies /api/* to the
# backend service via next.config.js rewrites (BACKEND_URL env).
#
#   docker build -t review-agent-frontend contract-review-agent/frontend

# ---- build stage ----
FROM node:22-alpine AS builder
WORKDIR /app

# Generate a fresh lockfile from the pinned package.json (no committed yarn.lock
# to avoid the version-mismatch rebuild loop).
COPY package.json ./
RUN yarn install

COPY . .
# BACKEND_URL is read at build time by next.config.js rewrites; default to the
# in-cluster backend Service DNS. Override at runtime via env if needed.
ENV BACKEND_URL=http://review-agent-backend:8000
RUN yarn build

# ---- run stage ----
FROM node:22-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# Next.js standalone output copies only the needed files into .next/standalone.
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
# public/ may not exist if the app has no static assets; create an empty one so
# the COPY doesn't fail.
RUN mkdir -p ./public

# Runtime env: the backend Service DNS inside the cluster.
ENV BACKEND_URL=http://review-agent-backend:8000

EXPOSE 3000
CMD ["node", "server.js"]
