# Local release verification — 20 September 2026

Verified in the relocated portfolio folder using the installed Python environment:

- Retail: 218 tests passed.
- Onboarding: 18 tests passed.
- Catalog: 30 tests passed.
- PO: 55 tests passed, including case-pack boundary cases.
- Portable Excel export: 8 tests passed across the four apps, including 600-row readback, numbers, literal formula-like text, empty sheets and colliding sheet names.
- All four app entry points rendered successfully with Streamlit AppTest from fresh local state.
- Real subprocess validation ran all three engines on both synthetic datasets. Corrected PO: 600 ready, zero blocked. Deliberate-error PO: 525 ready, 75 blocked.
- A shared-workflow scenario covered 600 vendors, 600 items and 600 PO lines, simulated acknowledgements, source correction invalidation, Finance/setup gates, failed Catalog retry, stale enrichment and owner updates, and Vendor/Category/Gender mismatches.

The Windows test harness worked around a local Python 3.14 temporary-directory ACL issue in the harness only. Streamlit emits a deprecation warning for the existing tooltip iframe implementation; app rendering passes. No production claim follows from these local checks.

Dependencies are declared for normal installation; Excel now requires only openpyxl rather than an application-specific Node cache. A GitHub Actions workflow is included for a fresh Python 3.12 installation, but has not run remotely. The local environment had Streamlit 1.59.2, pandas 3.0.3, Altair 6.2.2 and openpyxl 3.1.5. Legacy XLS import was not exercised; CSV and XLSX paths were tested.

The release includes only newly generated synthetic CSVs. The original secrets, runtime data and unverified datasets remain outside this release. Nothing has been pushed to a remote repository.

## 21 September update

- Launch Assurance source and scenario suite: 10 new checks; the Retail suite now passes 228 tests.
- Public `streamlit_app.py` entry passed Streamlit AppTest: initial source checks, expected INR 187,500 scenario delta, and independent state in a second visitor session.
- The demo uses browser-session state in public mode rather than the local shared demo database.
- Simplified local launch selection was exercised for demo, uploaded batch and new batch paths.
- Public hosting and remote CI remain unverified until authenticated publishing is complete.

## Remote verification — 21 September 2026

GitHub Actions on clean Linux / Python 3.12 passed all 339 tests (Retail 228, Onboarding 18, Catalog 30, PO 55, Excel 8), then passed the public-demo assessment, revalidation, Excel readback and visitor-isolation check. The first public-demo test run exposed a changed Streamlit testing API; the check now retrieves the export using its stable widget key.

Verified run: https://github.com/Deepali007-Agent/launch-assurance-command-center/actions/runs/35589700988

The source is public at https://github.com/Deepali007-Agent/launch-assurance-command-center . Streamlit deployment of this release still requires the owner's Cloud sign-in; the older hosted application is a separate build.


## 22 September improvements

Local checks passed: 246 Retail tests (18 new uploaded-logistics cases), 30 Catalog tests, the public demo check and a new uploaded comparison UI check covering reviewer persistence and export preparation. A 600-SKU integration run used the actual connected ledger gates and produced 1,800 alternatives. Existing workflow checks also passed Finance gates, failed handoff retry, upstream invalidation and stale assignment rejection.

Synthetic record-level benchmark: 30 Vendor, 45 Catalog and 75 PO error records detected with expected severity; all corrected records cleared, with no unexpected findings in generated negatives. This is authored regression evidence pending independent business review, not real-world accuracy or measured savings. Timing covers both dirty and corrected source-engine evaluation and excludes UI, ingestion and approval operations.

Local branch-inclusive coverage of launch_assurance and retail_workflow was 49% overall: 91% for the new uploaded model, 87% for the shared ledger and 96% for the original scenario engine. These are scoped measurements; UI checks and child source-engine processes were not collected into that run. CI now publishes per-app coverage rather than implying test counts mean full coverage.

Added fatal-error linting, compile checks, pinned direct dependencies, redacted structured logistics event logging, architecture/contracts and a formative study protocol. Lint found a missing import in the existing Catalog rework view; the import is corrected. No user study has run. Public hosting still requires owner sign-in; new batch logistics is available locally.
