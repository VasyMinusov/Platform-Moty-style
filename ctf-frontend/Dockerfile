# --- Сборка ---
FROM node:20-alpine AS build
WORKDIR /app

RUN corepack enable && corepack prepare pnpm@latest --activate

COPY pnpm-lock.yaml package.json ./
RUN pnpm install --frozen-lockfile

COPY . .
RUN pnpm build

# --- Раздача статики ---
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
