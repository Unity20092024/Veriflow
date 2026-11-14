# First collection recommendation — 2026-11-14

Recommend **lib.reviews → Mozilla Firefox**, extracted with **Apify's official Cheerio Scraper** (`apify/cheerio-scraper`). This is a permission-led, one-review technical pilot, not a claim that the Actor/source pair is already production-ready. No paid Actor run, database ingestion, source activation or source-registry expansion was performed for this recommendation.

## Why this pair

The eligibility gate was an affirmative, applicable source permission for automated retrieval and review-text reuse. Technical selection then considered actual review fields, stable provenance, minimal extraction, Actor maintenance and cost controls. A cheap marketplace scraper does not pass the permission gate by itself.

- **Source permission:** [lib.reviews terms](https://lib.reviews/terms) expressly welcome data download/mining and reuse, subject to the license, conduct rules and avoiding excessive resource use. Review/post text is licensed under **CC BY-SA 4.0**. The license [permits copying and commercial reuse](https://creativecommons.org/licenses/by-sa/4.0/) subject to attribution and its other conditions. This permission comes from the review source, not Apify or Firefox's software license.
- **Real product and review:** the [Mozilla Firefox product page](https://lib.reviews/mozilla-firefox) links to an [existing review with a permanent UUID URL](https://lib.reviews/review/48ea3813-0f63-4739-b659-0a361e9c99bf). It visibly supplies review text, a 3/5 rating, author attribution and a publication date of November 10, 2026. One existing review was observed; do not promise a larger sample or claim representative market coverage.
- **Technical fit:** the public page already contains the relevant HTML. [Apify's Cheerio Scraper](https://apify.com/apify/cheerio-scraper) uses HTTP and permits a custom extraction function, so a full browser, AI extraction and reviewer enrichment are unnecessary. The inspected stable `version-3` build is **3.0.24**, build ID **slvl0txyiL8qUoTR0**, Actor ID **YrQuEkowkNCLdk4j2**. These are observed candidate versions, not an enabled binding or a live-run validation.

## What may be retained, and conditions

The published terms establish a conditional reuse path for **review text**, including private storage; they do not waive attribution. Retain original text, native review UUID, publication date, 3/5 rating and scale, Firefox association, original permalink, collection time and source label. Also preserve the minimum licensing record: CC BY-SA 4.0 identifier/link, source terms URL, the public credit username and attribution link, and whether the text was changed. The source specifically requires crediting the author by username beside their contribution and recommends linking that credit to the source profile. That public credit is necessary attribution, not a reason to retain private reviewer details.

Keep emails, avatars, private identities and unrelated profile information out. Do not collect images or third-party embedded media: their rights can differ. Software/product metadata and site code have distinct licensing provisions; do not mislabel review text as CC0. Preserve original wording; if adaptations are later distributed, comply with the applicable attribution, change-indication and ShareAlike conditions. A future public website/export needs a separate publication review; no publication is proposed now.

[Current robots.txt](https://lib.reviews/robots.txt) disallows `/api/` for the wildcard user agent; the reviewed public product/review paths are not disallowed. This is an access signal, not the license. Use the public review page, not the disallowed API, and recheck terms/robots before any run. Do not load the site's database dump just to test one review.

## Proposed first live scope — not activated

Start from the single review permalink above. Configure one content page and one output row, maximum concurrency 1, zero automatic request retries, robots checking enabled, no proxy rotation, no asset/image collection, and no link discovery/enqueueing. Stop rather than bypass a refusal or rate limit. The Actor's relevant inspected inputs are `startUrls`, `pageFunction`, `maxPagesPerCrawl`, `maxResultsPerCrawl`, `maxConcurrency`, `maxRequestRetries`, `respectRobotsTxtFile`, `linkSelector`, `globs`, `pseudoUrls` and `proxyConfiguration`.

Set `maxPagesPerCrawl=1`, `maxResultsPerCrawl=1`, `maxConcurrency=1`, `maxRequestRetries=0`, `respectRobotsTxtFile=true`, and disable link selection/enqueueing explicitly. Zero is an **unlimited** value for several crawl limits, not a way to disable crawling. Robots retrieval can be an additional HTTP request. The Actor documents that page caps may be slightly exceeded in some crawling situations; one start URL with no link enqueueing minimizes that risk.

Expected outcome once authorized and supported: one normalized, attributed review in Supabase; a rerun produces zero new review rows and records a duplicate. Never create additional reviews to fill a target count. Current offline fixtures contain only marked placeholder text; actual review text was not copied into Git.

## Cost and current implementation gates

Cheerio Scraper is **pay per usage**, not a fixed price per review. Apify's [pricing page](https://apify.com/pricing) currently lists Free/Starter compute at $0.20 per CU, with one CU equal to 1 GB running for an hour. A hypothetical 1 GB, 60-second run has a compute component of about **$0.0033**, excluding other charges. This is an illustrative component, not a quote, measured runtime, approved budget or total-cost cap. Dataset operations, data transfer, storage and any selected proxies can add charges. Review the actual account plan and spending controls before execution.

**Do not bypass the existing cost guard.** Veriflow currently accepts paid starts only for reviewed pay-per-event configurations without separately billed runtime usage. This Actor is correctly blocked today. A usage-cost policy must be implemented/reviewed first, with memory/runtime/request/byte limits and appropriate account spending controls. The Actor also advertises full permissions by default; verify operation under the existing limited-permission policy rather than silently widening access.

Additional gates:

1. `lib.reviews` is outside the current 42-source catalog. It is recorded only as a proposed source, not silently added or enabled. An eventual authorization should cite the published terms/license, exact product/review scope, collection method and required attribution conditions.
2. Veriflow currently drops reviewer fields and has no dedicated review-license/attribution storage. Add minimal required licensing/credit persistence before ingesting CC BY-SA material. Do not use the current field projection to strip required attribution.
3. The Actor needs a reviewed extraction/mapping and array-valued `startUrls` target validation. It must derive the native rating/date and validate the Firefox association from source data, with no guessed dates, ratings or generated review text. Test this offline first.
4. An `APIFY_TOKEN` binding and a verified application PostgreSQL route are still missing in this environment. Actor existence and an open content license do not resolve those execution prerequisites.

Until these gates are met, use `tests/fixtures/proposed_libreviews_firefox.json` and the existing offline fixture suite. Keep all live sources disabled. No auth records or active Actor bindings were created.

## Alternatives checked

| Candidate | Permission/fit finding | Decision for first test |
|---|---|---|
| Apple App Store + `thewolves/appstore-reviews-scraper` | Useful review fields and low listed event prices, but [Apple Media Services terms](https://www.apple.com/legal/internet-services/itunes/us/terms.html) restrict automated scraping/copying/analysis. The official owner-scoped API is a separate access path. | Do not use the scraper without applicable permission. |
| SourceForge + `reviewly/sourceforge-reviews-scraper` | [Review guidelines](https://sourceforge.net/about/review-guidelines) incorporate [Slashdot Media terms](https://slashdotmedia.com/terms-of-use/). No affirmative third-party review-storage grant was established. Its Actor also bills runtime usage separately and declared native review fields need further verification. | Not permission-confirmed; do not activate. |
| SaaSHub | [Terms](https://www.saashub.com/site/terms) license public alternatives lists/statistics under CC BY-SA, while user submissions remain user-owned. That is not a blanket review-text reuse grant. | Possible discovery-data route, not the first full-text review test. |
| Mangrove | [Terms](https://mangrove.reviews/terms) explicitly permit commercial review-dataset reuse with attribution, generally CC BY 4.0 or the per-review license. Its [API](https://docs.mangrove.reviews/) is promising, but this investigation did not verify a particular software-review record and matching Actor. | Strong secondary open-review source to investigate; not substituted for the verified Firefox example. |

Capterra Reviews stays in the existing catalog and remains unapproved. No inference of rights was made from any third-party Actor. Restrictive review platforms were not scraped for test data.

## Evidence and status

Research used primary source terms, the Creative Commons license, a public product/review page, robots.txt, and Apify-owned Actor/build metadata and documentation. Exa searches covered 35 results across source-rights, open-source alternatives, existing-product evidence and Actor-fit queries; results were filtered rather than treated as permissions. Primary pages were fetched to check the applicable clauses. Direct retrieval of Slashdot Media terms returned HTTP 403 while the search/fetch index exposed the page; that was not bypassed and no positive reuse conclusion is drawn from it.

Status: **published source reuse terms verified, subject to conditions; live activation not authorized or implemented**. The existing 42-source registry, Supabase rows, credentials, collection schedules and production review data are unchanged.
