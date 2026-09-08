import type { Db, Order } from "../types";

export type OrderSearch = {
  tenantId: string;
  since: Date;
  limit: number;
};

/** Current path: filters and sorts without a covering index. See docs/PLAN_SEARCH_INDEX.md. */
export async function searchOrders(db: Db, q: OrderSearch): Promise<Order[]> {
  const sql = `
    SELECT id, tenant_id, status, cents, created_at
    FROM orders
    WHERE tenant_id = $1 AND created_at >= $2
    ORDER BY created_at DESC
    LIMIT $3
  `;
  return db.query<Order>(sql, [q.tenantId, q.since, q.limit]);
}
