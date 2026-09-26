# Local automatic intake

Run `python run.py --port-offset 100 --auto-intake` to start the four local workbenches and a background intake worker. For already-running apps, run `python scripts/watch_intake.py` separately. Keep the process running; it checks every 10 seconds independently of the browser. Stop with Ctrl+C. One worker owns each inbox, protected by an OS lock.

## Test in Retail Intelligence

1. Put a sealed submission folder in `local_intake/inbox`. The supplied local test kit includes an error submission and a later correction for the same batch. Copy the error folder first, then inspect the result before copying the corrected folder.
2. Open Retail Intelligence and expand **Automatic intake · local folder**. This small panel refreshes every 10 seconds. Refresh the full page and choose **Automatic intake demo** in Choose launch when processing finishes.
3. Inspect Actions and Evidence. Automatic processing does not approve vendors, approve items, acknowledge ERP execution, or release POs. Missing human approvals can still block corrected records.
4. Copy the corrected folder into the inbox. The same batch receives new versions for changed records; affected approvals become stale under the existing workflow rules.

## Your own files

Prepare CSVs named vendor.csv, catalog.csv and po.csv. Existing dataset templates apply. To submit safely:

`python scripts/submit_intake.py YOUR_FOLDER --batch YOUR_STABLE_BATCH_KEY --name "Your launch" --actor "Your name"`

This copies the files to a temporary folder, hashes their contents and atomically seals the submission into the inbox. The worker starts validation without another button click. An upstream exporter can perform the same sealing step. Never edit an already-sealed folder: submit a new revision with the same batch key. The helper automatically increments revisions based on inbox history; retain that history locally. Concurrent producers must allocate distinct increasing revisions; competing or stale revisions are rejected.

Optional inventory.csv and shipments.csv must arrive together. Add launch.json containing launch_date (YYYY-MM-DD) and horizon (1–31 days). Logistics is accepted only when its required commercial values and references validate. A rejected logistics input leaves the previous input unchanged; the status panel explains this. Recommendations always recompute against current source evidence and gates.

## Ownership and safeguards

The manifest can contain `owners` mapping an existing team name to `{"name":"Demo buyer","due":"2026-12-01"}`. Named assignments only fill currently unassigned requests, preserving human reassignment. Requests without mappings still route to the existing accountable teams and remain visibly unassigned. Approval requirements never change.

Submissions are additive updates by stable identifiers, not portfolio replacement. Omitting an existing SKU does not delete or cancel it. Catalog enrichment already applied in the workbench is preserved when unchanged original intake is replayed. Deliberate source content corrections can create a new version.

The manifest names the batch, submission ID, increasing revision, submitting actor, CSV filenames and SHA-256 hashes. Missing, incomplete, duplicate-key or unsafe-path files are rejected before source ingestion. Business blockers are saved as findings, not treated as worker failures. Completed submissions are not processed again. Changed content under the same submission ID and stale revisions are rejected.

An interrupted stage retries every 10 seconds using idempotent source writes and current-version Catalog receipts. Previously saved stages remain visible; this is not one cross-application transaction. Later revisions wait until the interrupted submission completes or is explicitly cancelled in the panel. Cancellation retains evidence. Correct files require a new sealed submission. Restarting the worker recovers interrupted processing from the local ledger.

This local prototype trusts access to the inbox and recorded actor names. It has no role authentication, cloud-folder connector, email notifications or real ERP/carrier actions. Runtime files, logs, inboxes and databases are excluded from Git. Use fictional data for demonstrations. Keep only one configured inbox per workflow database.
