# Isolated Mangrove connector patch for the existing worker

**Inactive integration artifact, not a deployment or approved collection scope.**
Replit's working worker and dashboard are authoritative. The user reports 11
genuine reviews across 11 software products; earlier Codex snapshots are historical,
not a newer count. No live source or database was contacted to develop this patch.

## Files to selectively port

`connector.py` is standalone standard-library Python. It has no imports from the
Codex application, SQL, migrations, credential handling, environment loading,
queue creation, scheduler, background threads, dashboard code or product campaign.
`test_connector.py` uses synthetic fixtures and injected transports exclusively.
Importing either connector module does not fetch data. Preserve all existing
Replit code; do not replace its worker with Codex's `application-worker`.

This is a Python integration contract, not a claim that the unavailable Replit
source has been patched or its runtime language verified. If its worker is not
Python, port this contract at the existing connector boundary rather than starting
another application or a competing worker.

## Worker boundary

1. Keep the feature disabled. A new approved scope is required before any live
   retrieval. The declined two-product batch is not reusable authorization.
2. Replit's **Breadth First** strategy chooses a distinct, verified software
   product from its existing catalog and establishes its exact Mangrove subject
   URL. `SoftwareProduct(subject, name)` represents that existing mapping. The
   connector does not infer that arbitrary websites are software, create products,
   choose categories or certify software merely because an API returns a review.
3. Supply the reviewed source-terms digest and existing worker authorization
   callback when eventually enabling the connector. The callback receives the
   source ID and software mapping and must return exactly `True` only when the
   current approved scope, source enablement, full-text license permission,
   authorization expiry/revocation and product mapping all permit this operation.
   Failure/exception denies access. No grant is created or automatically renewed.
4. Invoke `fetch_page` for one existing work item. The default page size is **one
   candidate**, not a depth-first sweep. Every call verifies the source terms and
   returns after one API page; there is no automatic pagination or second-product
   traversal. Replit decides whether its breadth quota justifies another visit.
5. Persist normalized records through the existing ingest path, revalidating scope
   and mapping in its existing transaction. Preserve its native-ID/content dedupe,
   license rows, counters, leases, completion receipts and exports. Revalidation
   in the connector cannot replace the worker's final transactional check.
6. Store `next_offset` only in the worker's existing supported cursor mechanism;
   it is an integer API offset, not a guessed HTML cursor URL. Offset advances
   over rejected candidates too. `more_possible` is only a full-page hint, not
   proof that more reviews exist. Offset pagination can shift during concurrent
   source edits; retain native-ID dedupe and do not claim exhaustive coverage.

No actual Replit handler names, schemas or persistence APIs are invented here.
The earlier comparison is in `docs/replit-selective-integration.md`. Codex's
`mangrove_collection.py`, admin job helpers, recurring migration and product
creation helpers are **not part of this isolated patch**. No DDL is required by
this fetching/normalization interface. If Replit lacks a suitable existing cursor
field, stop at that boundary; this task does not authorize a schema change.

## Source and spending constraints

HTTP goes only to the fixed public Mangrove terms/API endpoints. Subjects are API
query values, never fetch destinations. Redirects are rejected. HTTPS uses normal
certificate verification; no credentials or paid API are involved. Every request
has a 20-second timeout, 1 MB response bound and at least two-second spacing within
the connector instance. Total instance requests default to eight (configurable
2–30), including policy requests; there are no hidden retries. Preserve the
existing worker's persistent source-wide pacing, quotas and cooldowns across
instances/restarts. The connector's in-memory limits do not replace those controls.

Terms must match the exact reviewed SHA256 digest and contain the reviewed license
conditions. A changed digest stops retrieval, not an automatic approval. Reviews
must match the selected exact software subject and preserve the API native ID, text,
publication date and 0–100 rating. Only CC-BY-4.0 is accepted; the documented
default applies solely when individual license fields are absent. Explicit null,
unknown or conflicting licenses are rejected, including imported CC-BY-SA text.
JWTs, issuer keys, aliases and unrelated identifying fields are omitted.

Keep the original native review hyperlink, source credit, license and modification
notice beside any retained text and in private exports. The connector returns
those fields; their actual display/export persistence remains the existing app's
responsibility. It stores nothing itself. Do not publish or purchase services.

## Fixture validation

From the repository root, run the standard-library unittest module
`integration_patches.mangrove.test_connector`. It covers default-off behavior,
scope revocation, exact terms matching, one-candidate breadth behavior, cursor
progress on rejected licenses, native provenance/rating, intra-page deduplication,
request bounds, redirects, cooldown signals and sanitized failures. This is
independent offline verification, not a new live ingestion demonstration.

Future proposed scopes must specify distinct software-product coverage and
category diversity first, with genuine source evidence. The connector's support
for a worker-selected URL is not evidence that a particular additional product
has accessible licensed reviews. No new collection scope is proposed here.

Validation result for this patch: **nine independent offline tests passed**, plus **15 existing connector/license regression tests**. No existing application implementation file, migration or live configuration was modified.
