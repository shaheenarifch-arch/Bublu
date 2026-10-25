# BUBLU AI Phase 1

Autonomous Amazon + CJ Dropshipping agent starter under ATLAS.

## Included
- Product Discovery and profitability scoring
- Amazon listing generation via RAMBO
- Pricing intelligence
- Competitor alert logic
- Order automation interface for CJ
- Profit intelligence and daily executive reports
- PostgreSQL schema, Fastify API, Next.js dashboard, worker schedules, seed data, Docker infrastructure

## Run
```bash
cp .env.example .env
docker compose up -d
corepack enable
pnpm install
pnpm db:generate
pnpm db:validate
pnpm db:migrate --name init
pnpm db:seed
pnpm typecheck
pnpm test
pnpm build
```

Start in separate terminals:
```bash
pnpm dev:api
pnpm dev:admin
pnpm dev:worker
```

API: `http://localhost:8090` · Dashboard: `http://localhost:3002`.

## Production boundaries
Use current official Amazon Selling Partner API and CJ API documentation when configuring endpoints and authentication. This starter does not publish Amazon listings or submit supplier orders automatically. Keep approvals enabled until marketplace compliance, shipping, returns, invoice, and seller-of-record controls are validated.
