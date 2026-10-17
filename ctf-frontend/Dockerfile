# syntax=docker/dockerfile:1.7

# ═══════════════════════════════════════════════════════════════════════
# Stage 1: build — собираем SPA (Vite → /app/dist)
# ═══════════════════════════════════════════════════════════════════════
FROM node:22-alpine AS build

WORKDIR /app

# corepack + pnpm. Фиксируем major-версию pnpm, чтобы будущий
# `pnpm@latest` не сломал сборку (в package.json нет поля
# packageManager, поэтому без явной версии corepack не запустится).
RUN corepack enable && corepack prepare pnpm@9 --activate

# Сначала манифесты — слой с зависимостями кэшируется между сборками.
# Любое изменение src/** не будет триггерить повторный pnpm install.
COPY package.json pnpm-lock.yaml ./

# --frozen-lockfile: падаем, если lock не синхронизирован с package.json.
# Это защита от "локально работает, в CI — нет".
RUN pnpm install --frozen-lockfile

# Код и конфиги.
COPY . .

# Vite build → /app/dist. VITE_API_URL по умолчанию '/api' —
# значит, собранная статика будет ходить в /api/* на том же origin,
# который обслуживает nginx.
RUN pnpm build


# ═══════════════════════════════════════════════════════════════════════
# Stage 2: runtime — nginx:alpine + SPA-fallback
# ═══════════════════════════════════════════════════════════════════════
FROM nginx:alpine AS runtime

# Свой конфиг вместо дефолтного. Кладём ДО копирования статики,
# чтобы при пересборке этот слой не инвалидировался.
COPY nginx-frontend.conf /etc/nginx/conf.d/default.conf

# Собранная SPA.
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

# Foreground — иначе контейнер сразу завершится после старта nginx.
CMD ["nginx", "-g", "daemon off;"]