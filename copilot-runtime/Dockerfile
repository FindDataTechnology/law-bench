# syntax=docker/dockerfile:1
#
# law-bench admin-assistant CopilotKit runtime image (Node).
# Serves the AG-UI/GraphQL chat endpoint on 0.0.0.0:3111/copilotkit plus a
# plain /health. Cluster-internal only (ClusterIP Service, no Ingress) — the
# public path is law-bench's admin-gated /copilotkit proxy.
#
#   docker build -t copilot-runtime -f copilot-runtime/Dockerfile copilot-runtime/
#
# Pure-JS deps: no apt packages, no build toolchain needed. NODE_IMAGE defaults
# to upstream; builders on networks where docker.io is unreachable override it
# with a mirror (see Jenkinsfile NODE_IMAGE_MIRROR for the same rationale).
ARG NODE_IMAGE=node:22-slim
FROM ${NODE_IMAGE}

# npm registry mirror: the build host reaches pypi/npm faster domestically
# (same reason the main image points apt at a domestic Debian mirror).
RUN npm config set registry https://registry.npmmirror.com

WORKDIR /app
COPY package.json ./
RUN npm install --omit=dev && npm cache clean --force

COPY server.mjs ./

ENV NODE_ENV=production \
    PORT=3111
EXPOSE 3111

USER node
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s \
  CMD node -e "fetch('http://127.0.0.1:3111/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", "server.mjs"]
