-- Category portion of upstream 20261115003835_private_administration_jobs.
-- Reuse Replit's existing durable collection jobs; no duplicate administration queue.
CREATE TABLE veriflow.categories (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),name text NOT NULL,
 CHECK(length(trim(name)) BETWEEN 1 AND 120)
);
CREATE UNIQUE INDEX categories_name_normalized ON veriflow.categories(lower(trim(name)));
CREATE TABLE veriflow.product_categories (
 product_id uuid NOT NULL REFERENCES veriflow.products(id) ON DELETE CASCADE,
 category_id uuid NOT NULL REFERENCES veriflow.categories(id) ON DELETE CASCADE,
 PRIMARY KEY(product_id,category_id)
);
CREATE INDEX product_categories_category_idx ON veriflow.product_categories(category_id,product_id);
ALTER TABLE veriflow.categories ENABLE ROW LEVEL SECURITY;
ALTER TABLE veriflow.product_categories ENABLE ROW LEVEL SECURITY;
CREATE POLICY runtime_access ON veriflow.categories
 TO veriflow_runtime USING(true) WITH CHECK(true);
CREATE POLICY runtime_access ON veriflow.product_categories
 TO veriflow_runtime USING(true) WITH CHECK(true);
REVOKE ALL ON veriflow.categories,veriflow.product_categories FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE,DELETE ON veriflow.categories,veriflow.product_categories TO veriflow_runtime;
