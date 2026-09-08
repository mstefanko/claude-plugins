# Plan: per-tenant search index on orders

Owner: platform. Target: ship behind a flag, no maintenance window.

## 1. Problem

The per-tenant "recent orders" search does a sequential scan on `orders`. At our largest
tenant (4.1M rows) the p95 is 2.8s, measured 2026-08-28 with `EXPLAIN ANALYZE` on a replica.
The query filters `tenant_id` and `created_at` and sorts by `created_at desc`.

Table size for sizing the build: `orders` holds 11.4M rows total across 47 tenants, from
`SELECT count(*)` on the 2026-09-05 replica snapshot. The index build scans all of it, not
one tenant's slice.

## 2. Current state

`db/schema.sql` defines `orders` with a primary key on `id` and a foreign key on
`tenant_id`. There is no composite index covering `(tenant_id, created_at)`, which is why
the planner falls back to a scan.

## 3. Approach

Add a composite index concurrently, then move the search path onto it behind a flag.
Concurrently, because `orders` takes writes continuously and a plain `CREATE INDEX` holds a
write lock for the duration.

## 4. Steps

1. Migration `db/migrate/2026_09_orders_tenant_created_idx.sql`:
   `CREATE INDEX CONCURRENTLY idx_orders_tenant_created ON orders (tenant_id, created_at DESC);`
   Run outside a transaction block. Expected duration: 43-57 minutes for all 11.4M rows,
   scaled from a 90-second build on the 400k-row staging copy (28.5x the rows, plus a margin
   for concurrent write load, which a concurrent build must wait behind). Abort and roll back
   per §5 if it exceeds 90 minutes.
2. Add flag `search.use_composite_index`, default off, in `config/flags.yaml`.
3. Change `src/search/orders.ts` to select the indexed query path when the flag is on. Both
   paths return the same shape; the old path stays until step 6.
4. Enable the flag for one internal tenant, then 10%, then all, one step per day.
5. Delete the old query path and the flag in a follow-up change.

## 5. Rollback

- Before the flag is enabled: `DROP INDEX CONCURRENTLY idx_orders_tenant_created;`. Nothing
  reads it yet, so this is safe at any point.
- If `CREATE INDEX CONCURRENTLY` fails partway it leaves an invalid index. Detect with
  `SELECT indexrelid::regclass FROM pg_index WHERE NOT indisvalid;` and drop it concurrently
  before retrying. This is the documented failure mode and the reason we check.
- After the flag is on: set `search.use_composite_index` to off. That restores the scan path
  in one config change with no deploy.

## 6. Validation

Every stage in §4 has its own gate. Do not advance until the current stage's criteria hold
for a full 24 hours. All four metrics already exist; no new instrumentation is needed.

Stage 4a, the internal tenant:

- `EXPLAIN ANALYZE` on that tenant's query shows an index scan on
  `idx_orders_tenant_created` and no sequential scan on `orders`.
- p95 for that tenant, from the `search.orders.duration_ms` histogram, drops below 300ms
  against the 2.8s baseline in §1.
- Zero increase in `search.orders.error_rate` for that tenant.

Stage 4b, 10% of tenants:

- Fleet-wide p95 from the same histogram stays below 300ms.
- Zero increase in `search.orders.error_rate` fleet-wide.
- Write throughput on `orders` stays within 5% of the trailing 4-week median from
  `db.orders.insert_rate`. A 4-week window rather than one week, because weekly volume
  swings enough that a single week is a noisy baseline.

Stage 4c, 100%:

- The same three 4b criteria, re-measured for 24 hours at full traffic. This is the largest
  blast radius, so it is gated, not assumed.
- Sequential scans on `orders` in `pg_stat_user_tables` stop increasing.

If any criterion fails at any stage, roll back per §5 and stop.

## 7. Out of scope

Full-text search, cross-tenant search, and changing the sort order. Each would change the
index definition and belongs in its own plan.
