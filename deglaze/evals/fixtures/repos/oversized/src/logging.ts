export function logRequest(route: string, ms: number, status: number): void {
  console.log(JSON.stringify({ route, ms, status }));
}
