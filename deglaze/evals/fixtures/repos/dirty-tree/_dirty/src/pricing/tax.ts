const RATES: Record<string, number> = { "us-ca": 0.0725, "us-ny": 0.08875 };

export function taxFor(region: string, subtotal: number): number {
  return subtotal * (RATES[region] ?? 0);
}
