-- Cover foreign keys identified by the live Veriflow performance advisor.
CREATE INDEX collection_runs_batch_id_idx ON veriflow.collection_runs(batch_id);
CREATE INDEX import_batches_authorization_id_idx ON veriflow.import_batches(authorization_id);
CREATE INDEX trends_research_source_id_idx ON veriflow.trends_research(source_id);
