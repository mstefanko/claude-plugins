# Plan: per-tenant search index on orders

Owner: platform. Target: ship it this sprint.

## 1. Problem

The per-tenant "recent orders" search is slow. Customers have complained. The query filters
`tenant_id` and `created_at` and sorts by `created_at desc`.

## 2. Current state

The `orders` table has no good index for this query, so Postgres scans it.

## 3. Approach

Add a composite index on `(tenant_id, created_at)` and point the search at it. This is a
standard fix and should be low risk.

## 4. Steps

1. Add the index.
2. Update the search query to use it.
3. Deploy.
4. Clean up anything left over.

## 5. Performance

The index should make the query much faster, probably by an order of magnitude. We will
batch the backfill if needed.

## 6. Validation

Test it. If the search feels fast, we are done.

## 7. Notes

We may want full-text search later, and cross-tenant search has been requested a few times,
so we should keep that in mind while we are in here.
