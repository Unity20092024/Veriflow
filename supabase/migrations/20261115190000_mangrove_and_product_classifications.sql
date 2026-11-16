-- Add Mangrove as a disabled, pending source. No authorization or product
-- mapping is created here, so the existing worker cannot collect automatically.
INSERT INTO veriflow.sources
  (id,name,url,category,provenance,policy_notes,collection_method,access_status,
   enabled,schedule_seconds,minimum_interval_seconds,full_text_allowed,
   required_license_id,attribution_required)
VALUES
  ('mangrove-reviews','Mangrove Reviews (CC BY 4.0 collection)',
   'https://mangrove.reviews','review_aggregation',
   'Published dataset/API terms verified 2026-11-15',
   'Documented public API only. Accept per-review CC-BY-4.0; reject incompatible licenses. Require native review attribution. Fixed audited software subjects only; do not retain issuer keys, JWTs, images, or private identity fields.',
   'authorized_api','pending_authorization',false,86400,3,false,
   'CC-BY-4.0',true)
ON CONFLICT (id) DO NOTHING;

INSERT INTO veriflow.categories(name)
VALUES
  ('Flashcards'),('Education software'),
  ('Simulation games'),('Video games'),
  ('Password managers'),('Security software'),
  ('Book cataloging'),('Library services'),
  ('Linux distributions'),('Operating systems'),
  ('Video hosting'),('Federated platforms'),
  ('Secure communications'),('Whistleblowing platforms')
ON CONFLICT ((lower(trim(name)))) DO NOTHING;

WITH classification(product_name,category_name) AS (VALUES
  ('AnkiDroid','Flashcards'),('AnkiDroid','Education software'),
  ('Euro Truck Simulator 2','Simulation games'),('Euro Truck Simulator 2','Video games'),
  ('KeePassXC','Password managers'),('KeePassXC','Security software'),
  ('LibraryThing','Book cataloging'),('LibraryThing','Library services'),
  ('Parabola GNU/Linux-libre','Linux distributions'),('Parabola GNU/Linux-libre','Operating systems'),
  ('PeerTube','Video hosting'),('PeerTube','Federated platforms'),
  ('SecureDrop','Secure communications'),('SecureDrop','Whistleblowing platforms')
)
INSERT INTO veriflow.product_categories(product_id,category_id)
SELECT p.id,c.id
FROM classification x
JOIN veriflow.products p ON lower(trim(p.name))=lower(trim(x.product_name))
JOIN veriflow.categories c ON lower(trim(c.name))=lower(trim(x.category_name))
ON CONFLICT DO NOTHING;

-- Remove only the generic label from these seven specifically identified
-- products. Preserve all review records and every other category association.
DELETE FROM veriflow.product_categories pc
USING veriflow.products p, veriflow.categories c
WHERE pc.product_id=p.id AND pc.category_id=c.id
  AND lower(trim(c.name))='software'
  AND lower(trim(p.name)) IN (
    'ankidroid','euro truck simulator 2','keepassxc','librarything',
    'parabola gnu/linux-libre','peertube','securedrop'
  );
