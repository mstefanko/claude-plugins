import { discountFor } from "./discount";

export function quote(subtotal: number, customerId: string): number {
  return subtotal - discountFor(customerId, subtotal);
}
