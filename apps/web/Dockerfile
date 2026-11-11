# syntax=docker/dockerfile:1
# The web image. Build it from the repository root (so every image is built the same way):
#   docker build -f apps/web/Dockerfile --target production -t revops-web .
FROM node:26-alpine AS base
WORKDIR /app
RUN apk add --no-cache libc6-compat

# ---- Dependencies ----
FROM base AS deps
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci

# ---- Development: the source is mounted over /app by docker-compose ----
FROM deps AS development
COPY apps/web .
EXPOSE 3000
CMD ["npm", "run", "dev", "--", "--hostname", "0.0.0.0"]

# ---- Builder ----
FROM deps AS builder
COPY apps/web .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# ---- Production runner ----
FROM base AS production
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000
RUN addgroup --system --gid 1001 nodejs && adduser --system --uid 1001 nextjs

COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD wget -qO- http://127.0.0.1:3000/login >/dev/null || exit 1
CMD ["node", "server.js"]
