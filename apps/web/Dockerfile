# Контекст сборки — корень монорепозитория (см. infra/docker-compose.yml).
FROM node:22.12.0-alpine AS builder
RUN corepack enable
WORKDIR /app
COPY apps/web/ ./
ENV NEXT_PUBLIC_API_URL=http://localhost:8001
RUN pnpm install --no-frozen-lockfile && pnpm build

FROM node:22.12.0-alpine AS runner
RUN corepack enable
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/package.json ./
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/next.config.mjs ./
EXPOSE 3000
CMD ["pnpm", "start"]
