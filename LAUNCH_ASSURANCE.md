# Launch Assurance Command Center

One connected, synthetic launch demonstrating how retail teams can act before incomplete product data and fulfilment disruptions become lost demand. Open Retail Intelligence and use **Choose launch**. The **Demo** entry includes all five domains; **Uploaded data** entries use your shared batches. Earlier saved assessments are in **History**. Uploaded batches now accept paired shipment/inventory CSVs and compare operational alternatives using current execution gates; see ARCHITECTURE.md.

## Eight-step demonstration

| Step | What the slice does |
|---|---|
| 1. Onboarding | All four fictional items pass the existing mandatory item-field contract and vendor validators. Human vendor/Finance approvals are explicit scenario assumptions. |
| 2. Catalog | The existing Catalog service detects missing material on LA-DRESS-B. It is held from release. |
| 3. Buying Ops | The existing PO engine flags LA-DRESS-C's 33.33% margin against a 45% floor. It is held until cost is corrected. |
| 4. Shipment | A transparent estimate adds observed milestone delay to promised arrival: A is four days late, D six days late. This is not a trained or live carrier forecast. |
| 5. Inventory | A daily ledger models demand, receipts and lost sales for four SKUs at Mumbai and Delhi over seven days. Held records are distinguished from stock shortages. |
| 6. Orchestration | Recommend partial release of A and D, expedite A by three days and move 65 units of D from Delhi to Mumbai. Each logistics action must add net margin; donor demand and safety stock are retained. |
| 7. Ownership | The queue provides team-role defaults clearly marked as demo roles. Assign/reassign a named owner and due date; changes persist in a separate local demo audit. |
| 8. Revalidation | Select simulated corrections/interventions, enter a simulation reviewer, and rerun source checks and the same daily stock ledger. Only corrected records become eligible. |

The small scenario intentionally uses four SKUs to make every dependency inspectable. It remains separate from the 600-row upload workflow. Matching fictional logistics inputs are now provided in demo/logistics/.

## Three-minute demo

1. Run the launch assessment. Inspect the partial-release recommendation, missing content, buying margin and location chart.
2. Open **Actions & revalidation**, assign an action, then retain all interventions and enter a clearly fictional reviewer name. Click **Simulate selected actions & revalidate**.
3. Return to **Launch plan** to compare impact. Inspect **Agent evidence** and its collapsed Excel exports for assumptions and daily calculations.
4. Change the expedite cost to INR 100,000, save assumptions, and reassess. The system no longer recommends that uneconomic expedite. Assumption changes invalidate previous results.

## Reconciled financial story

All figures are INR and modeled, not realized. The baseline assumes source-clear SKUs can sell without the new logistics interventions; held SKUs cannot sell. The revalidated scenario additionally requires the simulated release-review action.

| Seven-day measure | Unchanged baseline | Recommended logistics only | All corrections + interventions |
|---|---:|---:|---:|
| Fulfilled units | 190 | 315 | 665 |
| Unfulfilled units | 510 | 385 | 35 |
| Revenue | 285,000 | 472,500 | 997,500 |
| Action costs | 0 | 3,300 | 3,300 |
| Net margin | 171,000 | 280,200 | 568,950 |
| Revenue improvement versus baseline | 0 | 187,500 | 712,500 |
| Net margin improvement versus baseline | 0 | 109,200 | 397,950 |

Action costs comprise INR 2,000 expedited freight plus 65 transferred units × INR 20. Protected revenue equals incremental fulfilled units × retail price. Protected margin equals scenario gross margin minus intervention costs minus baseline gross margin. A single SKU/location/day ledger prevents overlapping action benefits being added twice. Negative deltas remain negative.

Assumptions: fixed daily demand, receipts before demand on arrival day, no backorders or substitution, no taxes/returns or other operating costs. Opening inventory is projected at launch, not current-day stock. The synthetic PO location code TX maps to Mumbai; Delhi represents existing donor inventory. Expedite capacity and transfer confirmations are assumed, not booked. The policy evaluates expedites then transfers; it is a feasible greedy sequence, not a globally optimal solution.

## What remains a future integration

Live shipment milestones, measured demand/forecast uncertainty, WMS inventory freshness, authenticated approvals and actual execution through ERP/carrier APIs remain future work. The new capability is a bounded scenario demonstration, not production predictive intelligence. It runs separately from uploaded shared batches and never changes their approvals.

Verification: ten new engine tests passed with all 228 Retail tests. Checks cover source gating, margin math, donor reserves, inventory conservation, unprofitable/on-time expedites, no-demand scenarios, missing release review and inability to bypass held SKUs. Streamlit interaction checks verified named assignment and the final INR 712,500 / INR 397,950 metrics. The live parent layout also executed its installed source engines successfully.
