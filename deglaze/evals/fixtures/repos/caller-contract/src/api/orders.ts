import type { Db, Order } from "../types";

/**
 * Orders for a tenant, newest first.
 *
 * Changed 2026-09-05: returns `null` instead of an empty array when the tenant has no
 * orders, so callers can tell "no such tenant" apart from "tenant with zero orders".
 */
export async function ordersForTenant(
  db: Db,
  tenantId: string,
  limit = 50,
): Promise<Order[] | null> {
  const rows = await db.query<Order>(
    `SELECT id, tenant_id, status, cents, created_at
       FROM orders
      WHERE tenant_id = $1
      ORDER BY created_at DESC
      LIMIT $2`,
    [tenantId, limit],
  );
  if (rows.length === 0) return null;
  return rows;
}

export async function orderById(db: Db, id: string): Promise<Order | null> {
  const rows = await db.query<Order>(`SELECT * FROM orders WHERE id = $1`, [id]);
  return rows[0] ?? null;
}
