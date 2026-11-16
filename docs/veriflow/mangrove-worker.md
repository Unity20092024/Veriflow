# Mangrove worker integration

Mangrove uses the existing persistent collection-job queue. The upstream native
client is reused for the fixed HTTPS API, terms check, CC-BY-4.0-only
normalization, bounded pagination, response size, rate-limit, and attribution
behavior. Accepted records go through Veriflow's ordinary import validation,
deduplication, license storage, and exports.

The database source row is seeded disabled and `pending_authorization`. This
change creates no authorization, source-product mapping, scheduled job, or
collection job. Enabling full-text retention or creating a grant requires
separate explicit review and approval. The worker also checks the exact source,
grant, terms URL, product subject and expected name before requesting any page.

The API uses 20 review entries per page and an offset cursor, capped at five
pages per product in this adapter. Unsupported per-review licenses are skipped
without relabeling. A new worker page rechecks the published terms. Original
ratings remain on their 0–100 scale. Attribution links are constrained to
`https://api.mangrove.reviews/review/<native-signature>`; other source-host
validation is unchanged. JWTs, issuer keys, and unrelated identity data are not
retained.

Verified official product identities for the category correction:

- [AnkiDroid manual](https://ankidroid.org/) — Android flashcard application.
- [Euro Truck Simulator 2](https://eurotrucksimulator2.com/) — truck-driving
  simulation video game.
- [KeePassXC](https://keepassxc.org/) — cross-platform password manager.
- [LibraryThing](https://www.librarything.com/) — book cataloging and library
  service.
- [Parabola GNU/Linux-libre](https://parabola.nu/) — GNU/Linux distribution.
- [PeerTube](https://joinpeertube.org/) — federated video hosting software.
- [SecureDrop](https://securedrop.org/) — secure whistleblower submission
  system.

The classification migration only changes the seven matching products'
category associations and seeds Mangrove as pending and disabled. It does not
modify reviews, existing authorizations, completed jobs, or source credentials.
