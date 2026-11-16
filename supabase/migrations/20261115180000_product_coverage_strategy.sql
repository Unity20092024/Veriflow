-- Prospective preferences only: NULL strategy preserves every existing batch.
ALTER TABLE veriflow.products
  ADD COLUMN canonical_product_id uuid REFERENCES veriflow.products(id),
  ADD COLUMN research_requested_at timestamptz,
  ADD CONSTRAINT products_not_self_alias CHECK(canonical_product_id IS DISTINCT FROM id);
CREATE INDEX products_canonical_idx ON veriflow.products(canonical_product_id);
ALTER TABLE veriflow.collection_jobs
  ADD COLUMN strategy text CHECK(strategy IN ('breadth_first','balanced','depth_first')),
  ADD COLUMN target_reviews integer CHECK(target_reviews BETWEEN 1 AND 10000),
  ADD COLUMN software_category_id uuid REFERENCES veriflow.categories(id);
-- No backfill: the original approved batch retains its exact scheduling.
ALTER TABLE veriflow.free_batches
  ADD COLUMN strategy text CHECK(strategy IN ('breadth_first','balanced','depth_first')),
  ADD COLUMN target_reviews integer CHECK(target_reviews BETWEEN 1 AND 10000);

CREATE VIEW veriflow.product_evidence WITH(security_invoker=true) AS
WITH identities AS (
  SELECT id,coalesce(canonical_product_id,id) AS root_id FROM veriflow.products
), evidence AS (
  SELECT i.root_id,r.id,r.review_text,r.fingerprint,
    lower(regexp_replace(split_part(split_part(s.url,'://',2),'/',1),'^www\.','')) AS source_host
  FROM veriflow.reviews r
  JOIN identities i ON i.id=r.product_id
  JOIN veriflow.collection_runs run ON run.id=r.run_id AND run.status='success'
  JOIN veriflow.authorizations a ON a.id=r.authorization_id AND a.revoked_at IS NULL
  JOIN veriflow.sources s ON s.id=r.source_id AND s.category<>'market_research'
  LEFT JOIN veriflow.review_licenses l ON l.review_id=r.id
  WHERE length(trim(r.original_url))>0
    AND (r.rating IS NOT NULL OR length(trim(r.review_text))>0)
    AND (NOT s.attribution_required OR
         (l.review_id IS NOT NULL AND length(trim(l.public_credit))>0
          AND length(trim(l.attribution_url))>0))
    AND (s.required_license_id IS NULL OR l.license_id=s.required_license_id)
)
SELECT p.id AS product_id,p.name,p.vendor,p.research_requested_at,
  count(DISTINCT e.fingerprint)::integer AS reviews,
  count(DISTINCT e.fingerprint) FILTER(WHERE length(trim(e.review_text))>0)::integer AS text_reviews,
  count(DISTINCT e.source_host)::integer AS independent_sources
FROM veriflow.products p LEFT JOIN evidence e ON e.root_id=p.id
WHERE p.canonical_product_id IS NULL
GROUP BY p.id;
GRANT SELECT ON veriflow.product_evidence TO veriflow_runtime;
