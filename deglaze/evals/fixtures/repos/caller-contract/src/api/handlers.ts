import { ordersForTenant, orderById } from "./orders";
import type { Db, Req, Res } from "../types";

/** GET /tenants/:id/orders */
export async function listOrders(db: Db, req: Req, res: Res) {
  const orders = await ordersForTenant(db, req.params.id, Number(req.query.limit ?? 50));
  return res.json({
    count: orders.length,
    total_cents: orders.reduce((sum, o) => sum + o.cents, 0),
    orders,
  });
}

/** GET /tenants/:id/orders/summary */
export async function ordersSummary(db: Db, req: Req, res: Res) {
  const orders = await ordersForTenant(db, req.params.id);
  const byStatus: Record<string, number> = {};
  for (const o of orders) {
    byStatus[o.status] = (byStatus[o.status] ?? 0) + 1;
  }
  return res.json({ by_status: byStatus });
}

/** GET /orders/:id */
export async function getOrder(db: Db, req: Req, res: Res) {
  const order = await orderById(db, req.params.id);
  if (!order) return res.status(404).json({ error: "not found" });
  return res.json(order);
}
