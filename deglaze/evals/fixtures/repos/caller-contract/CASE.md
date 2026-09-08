# R4 — defect visible only through the caller

Removed by the harness before the model runs.

The change: ordersForTenant now returns null instead of [] when a tenant has no orders
(documented in its doc comment, return type Promise<Order[] | null>).

Expected: Needs surgery or Nope, at least one Change item naming the caller.
src/api/handlers.ts has two unguarded consumers: listOrders does orders.length and
orders.reduce, ordersSummary does for (const o of orders). Both throw a TypeError on a
tenant with zero orders, which is a normal state and not an error.

Requires reading or grepping beyond the named file. Reviewing orders.ts alone cannot find
this, which is the point of the case.
