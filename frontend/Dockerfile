# Build context is the REPO ROOT, not frontend/ (see docker-compose.yml's
# `frontend` service: `context: .`, `dockerfile: frontend/Dockerfile`) — the
# one deliberate exception to this monorepo's frontend/backend build
# isolation. #41's docs/contribute pages render docs/API.md and
# CONTRIBUTING.md verbatim via a Vite `?raw` import at build time (so the
# site never carries a hand-copied, driftable duplicate of that prose) —
# those two files live at the repo root, one level above frontend/, so the
# build has to be able to see them. Nothing else about the frontend/backend
# split changes: no shared dependency files, no shared config, and
# frontend-deploy.yml's path filter includes docs/API.md and
# CONTRIBUTING.md for exactly this reason (see that workflow's comment).
FROM node:22-slim AS build
WORKDIR /app

COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN cd frontend && npm ci

COPY frontend/ ./frontend/
COPY docs/API.md ./docs/API.md
COPY CONTRIBUTING.md ./CONTRIBUTING.md

# Vite inlines import.meta.env.PUBLIC_* at build time, not runtime (see
# src/middleware.ts / api/client.ts call sites) — must be a build ARG, not
# a docker-compose `environment:` entry on the runtime stage below.
ARG PUBLIC_API_BASE_URL=http://app:8000
ENV PUBLIC_API_BASE_URL=${PUBLIC_API_BASE_URL}
RUN cd frontend && npm run build

FROM node:22-slim
WORKDIR /app

# Astro's Node SSR output isn't fully bundled — dist/server/entry.mjs still
# imports some packages (astro's own runtime, @astrojs/node) from
# node_modules at runtime. --omit=dev keeps this to production deps only.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --omit=dev

ENV HOST=0.0.0.0
ENV PORT=4321
COPY --from=build /app/frontend/dist ./dist

EXPOSE 4321
CMD ["node", "./dist/server/entry.mjs"]
