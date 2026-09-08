import { discountFor } from "./discount";
import { taxFor } from "./tax";

export function quote(subtotal: number, customerId: string, region: string): number {
  const discounted = subtotal - discountFor(customerId, subtotal);
  return discounted + taxFor(region, discounted);
}
