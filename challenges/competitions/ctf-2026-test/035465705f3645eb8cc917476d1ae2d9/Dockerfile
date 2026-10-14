FROM node:20-alpine

WORKDIR /app

# ── Backend deps ─────────────────────────────────────────────────────
COPY backend/package.json ./
RUN npm install --omit=dev

# ── Frontend: install + build ────────────────────────────────────────
COPY frontend/package.json ./frontend/package.json
RUN cd frontend && npm install

COPY frontend/ ./frontend/
RUN cd frontend && npm run build

# ── Backend code ─────────────────────────────────────────────────────
COPY backend/ ./

# ── Готовую статику — в ./static, исходники фронта убираем ──────────
RUN mkdir -p ./static \
    && cp -r ./frontend/dist/* ./static/ \
    && rm -rf ./frontend

EXPOSE 5010

CMD ["node", "server.js"]