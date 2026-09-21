# Publish the portfolio demo

The repository and the running demo are separate deliverables. GitHub stores the source; Streamlit Community Cloud runs the public demonstration.

## Streamlit Community Cloud

1. Push this repository to your GitHub account.
2. Sign in to Streamlit Community Cloud and create an app from that repository.
3. Select the branch containing this release and set the entry point to `streamlit_app.py` at the repository root. Use Python 3.12.
4. No secrets are needed. Dependencies are in `requirements.txt`.
5. Deploy, then verify Run launch assessment, Actions & revalidation, and Excel downloads before sharing the URL.

The public app uses a session-isolated fictional scenario. It does not start four local servers or link visitors to localhost. The source repository retains the four-workbench upload workflow for local evaluation using `python run.py`.

Each public browser session starts fresh. Closing/reconnecting the session can discard demo assignments and history. Do not upload real company data or use this as a production approval system. No carrier, inventory or ERP transaction is executed.

## Expected demonstration

- Initially 2 of 4 SKUs pass the source gates; content and buying margin hold the other two.
- Baseline unmet demand is 510 units across the modeled seven-day horizon.
- Recommended logistics actions model INR 187,500 incremental sales and INR 109,200 incremental net margin.
- Applying all proposed corrections and the simulated human review models 4 eligible SKUs, 35 unmet units, INR 712,500 incremental sales and INR 397,950 incremental net margin against the unchanged baseline.
- These numbers belong to this synthetic scenario; they are not observed business savings.

## Release checks

Run `python scripts/test_all.py`. Remote CI and public deployment must be checked after publishing; local tests alone do not verify hosting.
