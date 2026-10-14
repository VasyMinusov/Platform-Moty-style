const path = require('path');
const http = require('http');
const express = require('express');
const cors = require('cors');
const { ApolloServer } = require('@apollo/server');
const { expressMiddleware } = require('@apollo/server/express4');

const { typeDefs, resolvers } = require('./schema');

const PORT = process.env.PORT || 5010;

async function start() {
  const app = express();
  const httpServer = http.createServer(app);

  // ── Apollo Server ───────────────────────────────────────────────
  const apollo = new ApolloServer({
    typeDefs,
    resolvers,
    // Introspection выключен: клиенты должны знать схему заранее.
    introspection: false,
    csrfPrevention: false,
    plugins: [
      {
        async requestDidStart() {
          return {
            async willSendResponse(requestContext) {
              const q = requestContext.request.query || '';
              const ip =
                (requestContext.contextValue && requestContext.contextValue.ip) ||
                'unknown';

              // Логируем всё, что похоже на попытку достать флаг.
              if (/flag/i.test(q)) {
                console.log(`[AUDIT] suspicious query from ${ip}`);
                console.log(`[AUDIT]   query: ${q.replace(/\s+/g, ' ').slice(0, 200)}`);
              }
            },
          };
        },
      },
    ],
  });

  await apollo.start();

  // ── Middlewares ─────────────────────────────────────────────────
  app.use(cors());
  app.use(express.json());

  // ── GraphQL endpoint ────────────────────────────────────────────
  app.use(
    '/graphql',
    expressMiddleware(apollo, {
      context: async ({ req }) => ({
        ip: req.headers['x-forwarded-for'] || req.socket.remoteAddress,
      }),
    }),
  );

  // ── Статика фронтенда ───────────────────────────────────────────
  const staticDir = path.join(__dirname, 'static');
  app.use(express.static(staticDir));

  // SPA fallback: любые GET-запросы без файла → index.html
  app.get(/^\/(?!graphql).*/, (req, res) => {
    res.sendFile(path.join(staticDir, 'index.html'));
  });

  // ── Запуск ──────────────────────────────────────────────────────
  httpServer.listen(PORT, '0.0.0.0', () => {
    console.log(`[+] Ordo Tasks ready on http://0.0.0.0:${PORT}`);
    console.log(`[+] GraphQL endpoint: http://0.0.0.0:${PORT}/graphql`);
    console.log(`[+] Static dir: ${staticDir}`);
  });
}

start().catch((err) => {
  console.error('[FATAL]', err);
  process.exit(1);
});