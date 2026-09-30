FROM node:22-alpine

ENV NODE_ENV=production \
    WA_ENV=production \
    WA_MODE=backend \
    WA_BIND_HOST=0.0.0.0 \
    WA_LOCAL_PORT=8787

WORKDIR /app
COPY --chown=node:node *.mjs catalog.json welcome.png ./
USER node
EXPOSE 8787
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD node -e 'fetch("http://127.0.0.1:8787/health/ready").then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))'
CMD ["sh", "-c", "node preflight.mjs && exec node server.mjs"]
