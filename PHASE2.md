# BUBLU AI Phase 2

## Modules
1. `amazon-spapi`: normalized Amazon orders, catalog, and listings client foundation.
2. `competitor-monitor`: snapshot persistence and price/out-of-stock alerts.
3. `inventory-sync`: CJ stock snapshots and low-stock alerts.
4. `dynamic-pricing`: fee-aware safe pricing and recommendations.
5. `opportunity-engine`: product opportunity scoring and alerts.
6. `profit-intelligence`: daily margin, fees, ad spend, ROAS, and profit metrics.
7. `store-management`: multi-store operations.
8. `automation`: approval-aware automation rules and audit runs.

## Important controls
- Default autonomy is recommendation-only.
- Amazon listing publication, price changes, and CJ fulfillment must remain approval-gated until current API contracts, marketplace permissions, and seller compliance are validated.
- Product and competitor collection must use permitted APIs and terms-compliant sources.
- Never infer Amazon fee values; feed current fee estimates into the pricing endpoint.

## Migration
```bash
pnpm install
pnpm db:generate
pnpm db:validate
pnpm db:migrate --name phase2_intelligence
pnpm typecheck
pnpm test
pnpm build
```
