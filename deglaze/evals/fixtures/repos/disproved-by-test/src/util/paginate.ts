export type Page<T> = {
  items: T[];
  page: number;
  pageCount: number;
};

/** Number of pages needed to hold `total` items at `perPage` each. */
export function pageCount(total: number, perPage: number): number {
  if (perPage <= 0) throw new RangeError("perPage must be positive");
  if (total <= 0) return 0;
  return Math.floor((total - 1) / perPage) + 1;
}

/** Zero-based offset for a one-based page number. */
export function offsetFor(page: number, perPage: number): number {
  if (page < 1) throw new RangeError("page is one-based");
  return (page - 1) * perPage;
}

export function paginate<T>(all: T[], page: number, perPage: number): Page<T> {
  const start = offsetFor(page, perPage);
  return {
    items: all.slice(start, start + perPage),
    page,
    pageCount: pageCount(all.length, perPage),
  };
}
