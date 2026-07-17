FROM node:22.17.0-bookworm-slim AS toolchain

ENV PNPM_HOME="/pnpm"
ENV PATH="${PNPM_HOME}:${PATH}"

RUN corepack enable \
    && corepack prepare pnpm@11.4.0 --activate

WORKDIR /workspace

FROM toolchain AS dependencies

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml .npmrc ./
COPY apps/web/package.json apps/web/package.json

RUN pnpm install --frozen-lockfile --filter @axit/web...

FROM dependencies AS build

COPY apps/web apps/web

RUN pnpm --filter @axit/web lint \
    && pnpm --filter @axit/web typecheck \
    && pnpm --filter @axit/web test \
    && pnpm --filter @axit/web build

FROM node:22.17.0-bookworm-slim AS runtime

ENV HOSTNAME="0.0.0.0"
ENV NODE_ENV="production"
ENV PORT="3000"

WORKDIR /app

COPY --from=build --chown=node:node /workspace/apps/web/.next/standalone ./
COPY --from=build --chown=node:node /workspace/apps/web/.next/static ./apps/web/.next/static

USER node

EXPOSE 3000

HEALTHCHECK --interval=10s --timeout=3s --retries=6 \
  CMD ["node", "-e", "fetch('http://127.0.0.1:3000/health').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"]

CMD ["node", "apps/web/server.js"]
