# Retail Intelligence — portfolio prototype

A retail operations workflow and decision-support prototype connecting vendor onboarding, item readiness and buying requests. It explains what is blocked, which team must act next and what evidence is needed to progress.

Start with **Launch Assurance Command Center**, the default demo in Retail Intelligence: one synthetic launch connects onboarding, Catalog, buying, shipment and location-stock scenarios to partial release, expedite, reallocation, owners and modeled commercial impact. See [the eight-step walkthrough](LAUNCH_ASSURANCE.md). Shipment/inventory estimates are transparent scenarios, not live or trained forecasts. Use **Choose launch** to select a batch labelled **Uploaded data**; earlier saved assessments are under **History**.

It demonstrates deterministic validation engines, shared request tracking, owner reassignment, versioned evidence, human review and a **simulated** ERP handoff. It does not create transactions in a real ERP. Reviewer names are recorded, not authenticated against enterprise roles. Commercial exposure is modeled, not measured revenue recovery.

## Run locally

Use Python 3.11 or newer in a virtual environment. From this repository:

```sh
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# macOS / Linux instead: source .venv/bin/activate
python -m pip install -r requirements.txt
python run.py
```

| Application | URL | Responsibility |
|---|---|---|
| Retail Intelligence | http://localhost:8508 | Shared status, recommended actions, evidence and audit |
| Onboarding | http://localhost:8509 | Vendor information and mandatory item setup attributes |
| Catalog | http://localhost:8507 | Receives eligible items; validates and enriches product content |
| PO / Buying | http://localhost:8510 | Evaluates buying requests and upstream dependencies |

Stop with Ctrl+C. Start one workbench with `python run.py po`. If the ports are occupied, stop the old installation or use `python run.py --port-offset 100`. Navigation follows the configured ports when launched this way. The launcher binds to localhost; this is a local prototype, not a hardened public deployment.

All apps use the current Python environment. Excel exports use openpyxl in memory: no Node runtime, Codex installation or Desktop directory structure is required. Keep the `apps/` folders together; the entire repository can be moved or cloned anywhere. Runtime SQLite databases are created locally and excluded from Git. No API keys are needed for the core workflow. `.env.example` documents optional settings; it is not loaded automatically.

## Demonstrate the workflow

1. In Onboarding, create a batch, select it, and upload `demo/with_errors/vendor.csv` and `catalog.csv`. Validate once for vendor and item intake.
2. Open Catalog on the same batch and process received items. The item file belongs in Onboarding; Catalog handles subsequent enrichment.
3. In PO, choose the batch and upload `demo/with_errors/po.csv`. Validate the buying requests. Missing setup, mismatched Vendor/Category/Gender or blocking validation findings prevent downstream execution.
4. In Retail Intelligence, review the recommended actions, assign/reassign ownership, and inspect evidence. Upload the matching corrected files in the owning workbenches and revalidate to compare progress.
5. Record eligible human reviews and use explicitly simulated ERP acknowledgements in vendor → item → PO order. A correction invalidates dependent approvals/receipts until current evidence is reviewed again.

Every demo CSV contains 600 data rows. All identities, contact details, financial figures and identifiers are fictional. Contact domains and image links use example.com; images are placeholders. Tax and registration values are deliberately labelled invalid for real-world use. Generated GTIN-like values have check digits for format testing, not registration or ownership. See `demo/error_answer_key.csv` for deliberate defects. Regenerate dates and all demo data with `python scripts/generate_demo.py`.

## Quantity meaning

Currently `Total Quantity` means sellable units and `Case-pack` means units per shipping case. Quantity must be divisible by case-pack. Example: 60 units / 6 per case = 10 cases. Do not multiply 60 by 6 again. Included components, such as straps supplied with a bra, are a different concept and are not represented by the shipping case-pack field. Any future packs-based ordering needs explicit quantity and price units before changing totals.

## Verify

```sh
python scripts/test_all.py
```

Tests run separately per app to avoid module-name collisions. The source-rule matrix uses the bundled synthetic CSVs. Excel tests verify 600 rows, numeric values, empty outputs, valid sheet names and formula-like input preserved as text.

## Release scope and next phase

The release excludes live secrets, local databases, logs, history, installed dependencies, generated exports and unverified input datasets. Existing live application folders were not modified by release preparation.

Next phase: authenticated roles, a deployed multi-user data service, approved ERP APIs and delivery retries, and notifications to team systems. Saved launch analysis and connected request readiness are distinct views. No claim of production deployment, real ERP integration or quantified business savings is made.

## Public portfolio entry point

Deploy `streamlit_app.py` for a focused, session-isolated Launch Assurance demonstration. The public view runs the same included source validation engines and synthetic logistics scenario, without requiring four local servers. The standalone upload workbenches remain available locally. See [deployment instructions](DEPLOYMENT.md).

## Uploaded logistics and evidence improvements

For an uploaded batch in Retail Intelligence, expand **Upload shipment and inventory inputs**. Supply both CSVs using the header templates, set launch date/horizon and validate. `demo/logistics/` contains fictional inputs matching the 600-row source files. Use corrected valid commercial inputs before modeling; approval/setup gates still determine whether a SKU can proceed.

Compare three alternatives by SKU, inspect the +20% demand stress case, and record accept/reject/defer/override with an owner, due date and justification. This records a decision only; it does not execute transport or bypass approvals. Source edits make prior choices stale.

[Architecture and model contracts](ARCHITECTURE.md) · [Synthetic benchmark](benchmark/README.md) · [Formative study protocol](USABILITY_STUDY.md)

Run `python scripts/benchmark_validation.py` to reproduce the source-record benchmark. Expected labels are authored synthetic cases pending independent business review; ownership and handoff performance are not implied by detection metrics. Run `python scripts/quality_checks.py` after installing `requirements-dev.txt` for linting, static compilation and per-app coverage reports.
