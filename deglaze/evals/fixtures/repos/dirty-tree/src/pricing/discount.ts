const TIERS: Record<string, number> = { free: 0, pro: 0.1, enterprise: 0.2 };

export function discountFor(customerId: string, subtotal: number): number {
  const tier = tierOf(customerId);
  return subtotal * (TIERS[tier] ?? 0);
}

function tierOf(_customerId: string): string {
  return "free";
}
