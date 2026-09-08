import { test, expect } from "bun:test";
import { pageCount, offsetFor, paginate } from "./paginate";

test("pageCount pins every boundary", () => {
  expect(pageCount(0, 10)).toBe(0);
  expect(pageCount(1, 10)).toBe(1);
  expect(pageCount(9, 10)).toBe(1);
  expect(pageCount(10, 10)).toBe(1); // exactly full: one page, not two
  expect(pageCount(11, 10)).toBe(2);
  expect(pageCount(20, 10)).toBe(2); // exactly full again
  expect(pageCount(21, 10)).toBe(3);
  expect(pageCount(1, 1)).toBe(1);
  expect(pageCount(7, 3)).toBe(3);
});

test("pageCount rejects a non-positive page size", () => {
  expect(() => pageCount(10, 0)).toThrow(RangeError);
  expect(() => pageCount(10, -1)).toThrow(RangeError);
});

test("offsetFor is one-based", () => {
  expect(offsetFor(1, 10)).toBe(0);
  expect(offsetFor(2, 10)).toBe(10);
  expect(() => offsetFor(0, 10)).toThrow(RangeError);
});

test("paginate returns the right slice on the last partial page", () => {
  const all = Array.from({ length: 11 }, (_, i) => i);
  const last = paginate(all, 2, 10);
  expect(last.items).toEqual([10]);
  expect(last.pageCount).toBe(2);
});
