# ResearchOS TECT X
## Architecture and Advanced Systems Engineering

ResearchOS is a local Phase I research prototype for Topological Epistemic Control Theory (TECT). It tracks how candidate claims move from generation through validation and assurance, and records the evidence, policy, and rationale behind each decision.

### Run the pilot

Use Python 3.10 or later. The prototype uses the Python standard library and SQLite.

```sh
python3 -m researchos --db researchos.sqlite3 pilot > report.json
python3 -m unittest discover -s tests -v
```

The pilot ingests four synthetic model outputs. It checks each against a reference answer, compares source digests, verifies the declared input set, and repeats the calculation with a second implementation. The report contains the assurance record for each case and compares the controller with two deterministic baselines.

| Condition | Claims accepted | Acceptances with a seeded defect |
| --- | ---: | ---: |
| Accept every candidate | 4 | 3 |
| Verify arithmetic only | 3 | 2 |
| Apply the TECT pilot policy | 1 | 0 |

These fixtures exercise controller behavior. The four-condition human and model study, throughput targets, quantitative stability margins, and convergence results remain research work. The reproduction paths use the same fixture inputs and run in the same process.

### Work with a claim

Each command accepts a JSON object and returns JSON. Use the ID printed by `register` in subsequent operations.

```sh
python3 -m researchos register '{"statement":"The total of 2 and 3 is 5.","source":"model-run:example","actor":"ingestion"}'
python3 -m researchos transition '{"claim":"CLAIM_ID","desired":"UNVERIFIED","actor":"ingestion","role":"researcher","rationale":"Registered for review"}'
python3 -m researchos add_evidence '{"claim":"CLAIM_ID","kind":"support","outcome":"PASS","source":"worksheet:example","method":"Worksheet inspection","source_group":"worksheet","detail":"The recorded inputs are 2 and 3.","actor":"reviewer"}'
python3 -m researchos assurance '{"claim":"CLAIM_ID"}'
```

| Command | JSON arguments |
| --- | --- |
| `register` | `statement`, `source`, `actor` |
| `add_evidence` | `claim`, `kind`, `outcome`, `source`, `method`, `source_group`, `detail`, `actor` |
| `link` | `claim`, `relation`, `target`, `actor` |
| `transition` | `claim`, `desired`, `actor`, `role`, `rationale` |
| `resolve` | `claim`, `evidence`, `rationale`, `actor`, `role` |
| `assurance` | `claim` |

Python adapters can call the same methods on `researchos.controller.Controller(database_path)`. Close the controller when finished. The CLI returns status 1 for a policy denial and 2 for invalid input or a storage error.

### Pilot policy `tect-pilot/1`

`GENERATED → UNVERIFIED → SUPPORTED → ADVERSARIAL_TEST → REPRODUCED → VALIDATED → STABLE → ASSURED`

| Gate | Required evidence and governance |
| --- | --- |
| Supported and adversarial test | Traceable origin, passing support, and no unresolved failure or contradictory claim |
| Reproduced | Passing contradiction, source integrity, and dependency integrity checks, no unresolved uncertainty in those checks, and passing reproduction from a source group distinct from supporting evidence |
| Validated and stable | Reviewer or approver, passing validation after the most recent contest, resolved uncertainty, and validated or higher dependencies |
| Assured | Approver and assured dependencies |

Evidence outcomes are `PASS`, `FAIL`, and `UNCERTAIN`. The source group is a declared correlation identifier. `STABLE` records satisfaction of the three pilot challenge gates. The controller does not estimate a quantitative perturbation bound.

Relationships point from a claim to its evidence-relevant claim. `depends_on` and `derives_from` define dependencies and disallow cycles. The graph also records `supports`, `contradicts`, `reproduces`, `qualifies`, and `invalidates`. Contradiction and invalidation links block promotion while their target remains active. Failed evidence and material relationship changes can contest claims. Changes to validated, stable, or assured claims trigger reassessment that propagates to downstream dependencies. A reviewer or approver can record an evidence resolution and return a contested claim to `UNVERIFIED` or move it to `REJECTED`.

Assurance exports include the claim's current state and state version, provenance, latest validation time, evidence, graph links, evidence resolutions, the perturbation family, and the accepted and blocked decisions with their policy version. The same transaction commits a state change and its ledger entry.

The interface assumes a trusted local operator. Actor names, roles, and evidence provenance are supplied by the caller. The ledger is append-only through the application interface. A deployment with untrusted writers would require authenticated roles, independent evidence ingestion, and protected audit storage.
