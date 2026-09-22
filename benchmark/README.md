# Synthetic validation benchmark

Synthetic authored cases; expectations require independent business review. Record-level metrics, not per-finding metrics. Negative cases are the remaining generated records. This is regression evidence, not real-world detection accuracy. Ownership and handoff correctness require the separate workflow suite; they are not inferred from source severity.

| Domain | Records | Precision | Recall | Critical recall | False positives | Cleared corrections |
|---|---:|---:|---:|---:|---:|---:|
| vendor | 600 | 100.0% | 100.0% | 100.0% | 0 | 30/30 |
| catalog | 600 | 100.0% | 100.0% | 100.0% | 0 | 45/45 |
| po | 600 | 100.0% | 100.0% | 100.0% | 0 | 75/75 |
