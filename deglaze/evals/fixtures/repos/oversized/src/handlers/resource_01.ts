import { logRequest } from "../logging";

export async function handle_01(req: { id: string }): Promise<{ ok: boolean }> {
  const started = Date.now();
  const result = { ok: Boolean(req.id) };
  logRequest("resource_01", Date.now() - started, result.ok ? 200 : 400);
  return result;
}
