export type Order = {
  id: string;
  tenant_id: string;
  status: string;
  cents: number;
  created_at: string;
};
export type Db = { query<T>(sql: string, params?: unknown[]): Promise<T[]> };
export type Req = { params: Record<string, string>; query: Record<string, string> };
export type Res = { json(body: unknown): unknown; status(code: number): Res };
