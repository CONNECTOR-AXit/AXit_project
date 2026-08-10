FROM node:22.17.0-bookworm-slim AS build

WORKDIR /app
RUN corepack enable && corepack prepare pnpm@11.4.0 --activate
COPY . .
RUN pnpm install --frozen-lockfile
RUN pnpm --filter @axit/main-goal-frontend build

FROM node:22.17.0-bookworm-slim AS runtime

ENV NODE_ENV=production
ENV PORT=3000
WORKDIR /app/AXit_project-main_goal_frontend
COPY --from=build --chown=node:node /app/AXit_project-main_goal_frontend/package.json ./package.json
COPY --from=build --chown=node:node /app/AXit_project-main_goal_frontend/server ./server
COPY --from=build --chown=node:node /app/AXit_project-main_goal_frontend/dist ./dist
EXPOSE 3000
USER node
CMD ["node", "server/server.mjs"]
