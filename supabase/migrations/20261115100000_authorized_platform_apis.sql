-- Enable adapter selection only for these still-disabled, unapproved sources.
-- This does not grant access, create a product mapping, or enable collection.
UPDATE veriflow.sources
SET collection_method = 'authorized_api'
WHERE id IN ('google-play','apple-app-store')
  AND enabled = false
  AND access_status = 'pending_authorization'
  AND collection_method = 'approved_import'
  AND NOT EXISTS (
    SELECT 1 FROM veriflow.authorizations a
    WHERE a.source_id = veriflow.sources.id
  );
