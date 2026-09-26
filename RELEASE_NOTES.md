# Portfolio release — 26 September 2026

This release freezes the local demonstration scope for portfolio review.

## Demonstrated
- One versioned vendor/item/PO batch shared across Onboarding, Catalog, Buying and Retail Intelligence.
- Local monitored-folder intake with integrity checks, revisions, retries and explicit human gates.
- Connected dashboards, named next steps, documented issue origin separate from responsible owner.
- Actionable tasks separated from downstream waiting requirements using current validation/approval gates.
- Distinct source tasks and unique affected SKU counts. One vendor approval can affect many SKUs; counts across requirements overlap.
- Downloadable SKU overview, requirement detail, assignments, team sheets and PO requirements in Excel.
- Synthetic logistics scenarios and reviewed alternatives; no real ERP execution or trained demand/delay forecasting.

## Timing boundary
SLA targets, actionable elapsed time and completed stage TAT are not measured in this release. Existing due dates and source-version age are not substitutes. Pending requirements must not be described as SLA breaches. A future timing model needs explicit stage policies, activation/completion events, working calendars, pause rules and revision/reopen handling.

## Review policy
Catalog content checks and item approval can proceed while vendor Finance approval is pending when Catalog source checks permit review. Vendor setup confirmation waits for vendor validation and Finance approval. Item and PO execution still require their current upstream gates. Named reviewers are recorded, not enterprise-authenticated.

## Demo sequence
1. Create one shared batch in Onboarding and upload synthetic vendor/catalog files from demo/with_errors.
2. Process the received Catalog queue; upload the matching PO file in Buying.
3. Open Item Onboarding and compare Action needed now with Waiting on another step. Download the SKU action register.
4. Upload matching corrected IDs, revalidate and review current versions. New IDs add records rather than replace other IDs.
5. Record eligible human decisions and simulate vendor, item and PO setup/receipt steps. Inspect the audit trail.

## Deferred
Cloud/shared-drive ingestion, production identity/authorization, real ERP/carrier integrations, stage SLA/TAT measurement and externally validated business outcomes. These are next-phase capabilities, not completed functionality.

## Release verification
375 tests passed across Retail (264), Onboarding (18), Catalog (30), Buying (55) and root integration checks (8). Fatal lint and compilation passed. The public demo, revalidation/export readback and authored synthetic validation benchmark passed. These are prototype checks, not evidence of production effectiveness.
