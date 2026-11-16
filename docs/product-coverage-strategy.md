# Product coverage and evidence strategy

Veriflow collects authentic software-review evidence for a **future software
review and affiliate-content website**. Product/category diversity takes priority
over raw review volume. This release does not build or publish that website.

## New jobs

- **Breadth First** (default): aim for 5 total unique evidence reviews per
  canonical product; prefer products with zero/fewer reviews, then poorly covered
  software categories. In the direct per-review discovery queue, alternate
  products as their actual ingested evidence grows.
- **Balanced**: default target 10, revisit products in five-review bands while
  balancing categories.
- **Depth First**: default target 30. Select a particular product in Collection
  to gather deeper evidence for manual editorial research.
- Targets are adjustable per job (1–10,000), not database storage caps.
  Existing authentic reviews are never deleted to enforce a target.
- New generic jobs retain ceilings of 500 new reviews, 1,500 attempts,
  10 fetched pages per source-product item, and 48 hours from job creation.
  Connector authorization and source-specific ceilings may be much lower.
- Scope, permissions, attribution, pagination, deduplication, retries and the
  existing no-paid-Apify safeguard continue to apply. Strategy is not source
  permission. Unsupported or unapproved discovery is not activated.
- Existing jobs/batches have NULL strategy and continue their original path.
  They are not restarted, rearmed, backfilled, or given new deadlines.

`python -m veriflow collection-start --scope all_eligible`
defaults to Breadth First. Example **only after approving the source scope**:
`python -m veriflow collection-start --scope product --product PRODUCT_UUID
--strategy depth_first --target-reviews 30`.

Generic paginated connectors may return more reviews than a product needs in a
single response. Only the unique allowance is queued; unused response entries
are not retained. A later deeper job starts from the source again and skips
previously stored duplicates. This trades some repeated reading for avoiding
unnecessary full-text retention; it is not a permanent historical ceiling.

## Evidence and research

The authenticated **Product coverage** page counts canonical products with
1+, 3+, 5+ and 10+ unique evidence reviews, software-category coverage,
unclassified products, evidence gaps, source-host coverage and selected research.
Search/filter options distinguish uncovered, insufficient, ready and queued.

Evidence requires successful ingestion, a non-revoked authorization, a source
link, content/rating, and any attribution/license mandated by that source.
An expired collection authorization is not itself revocation of an already
granted continuing content license. Counts do not certify customer claims.

Three text-bearing reviews is the initial **manual deeper-research** threshold,
not a publication threshold or claim that evidence is sufficient for an article.
An administrator may select a product with one review for investigation; the
dashboard continues to warn that evidence is limited. Zero-evidence products
cannot enter the review-based research selection. No article generator or
automatic publication exists. Recheck source links, licensing, product identity,
review substance and opposing evidence before writing editorial conclusions.

Independent-source counts mean distinct source hostnames (normalizing `www`),
not review/import counts. Different domains can still share an owner, so
editorial independence must be verified manually.

## Identity safety

Existing mappings are reused. Prospective discovery normalizes Unicode,
case and whitespace, recognizes owner-confirmed aliases and stops on ambiguous
matches. Do not infer product identity from a shared marketplace/hosting domain.
Different names/domains are not automatically merged without reliable identity
evidence.

On Product coverage, an authenticated administrator can confirm two existing
names represent the same software. This creates one canonical group without
deleting or moving reviews. Chains/cycles and changes during active collection
are rejected. Category/evidence counts then aggregate the aliases.

## Deployment

Apply the additive migration
`supabase/migrations/20261115180000_product_coverage_strategy.sql`
once as the existing database owner before restarting Python services. The view
uses PostgreSQL security-invoker semantics, preserving underlying RLS. It grants
only view SELECT to the existing runtime role.

The optional `python -m scripts.apply_product_coverage_migration` helper uses the
already-configured temporary administrator Secret if it is still available;
otherwise apply the SQL through the owner's Supabase SQL interface. It never
changes a password, connection Secret, account, source permission, authorization,
review, or existing job. Do not create new credentials just to run this helper.
