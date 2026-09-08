-- Trimmed to the tables the plan touches.

CREATE TABLE tenants (
  id         uuid PRIMARY KEY,
  name       text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE orders (
  id         uuid PRIMARY KEY,
  tenant_id  uuid NOT NULL REFERENCES tenants (id),
  status     text NOT NULL,
  cents      bigint NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- Indexes on orders:
CREATE INDEX idx_orders_status ON orders (status);
-- No composite index on (tenant_id, created_at). See docs/PLAN_SEARCH_INDEX.md.
