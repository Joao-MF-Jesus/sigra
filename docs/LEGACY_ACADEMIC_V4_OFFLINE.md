# Legacy evidence: offline, additive academic v4 adapter

Decision: `LEGACY_OFFLINE_INTEGRATION_PARTIAL`. This is evidence integration,
not activation, publication, an operational ranking or academic readiness.

## Scope and source of truth

`legacy_academic_v4_evidence_v1.json` individually reviews canonical IDs 1–34.
`legacy_academic_v4.py` accepts explicit local `SourceArchive` roots, verifies
all pinned source bytes, then reuses the unchanged v3 baseline and v4 evaluator.
It has no source discovery, HTTP, database connection or application startup hook.
No v3 contract, input, formula, weight, threshold or fingerprint is replaced.

The manifest contains public provenance and reviewed field bindings, not raw
responses or PDFs. FIPE receipts, the July cache, five official PBEV PDFs
(2017–2021) and their parsed snapshots remain external/already existing. Each
PBEV binding pins the PDF hash, parsed snapshot hash, page, row and row hash.
PDF rows were visually reviewed and subsequently reparsed from the pinned PDFs.

## Individual admissions and remaining holds

Exact catalog trim membership and compatible FIPE/PBEV year, fuel, engine and
transmission were admitted for IDs **2, 3, 4, 5, 8, 9, 10, 14, 15, 16, 20, 22,
29, 30, 31, 32, 33, 34**. Shared PBEV trim rows are consumption evidence for the
listed mechanical configuration, not permission to copy other trims' equipment.
The explicit manufacturer labels `GM - Chevrolet` and `VW - VolksWagen` are
checked as exact FIPE labels, not normalized through similarity matching.

Of the original seven identity holds, only Ka SE (33) is resolved here: FIPE
lists SE/SE Plus and PBEV lists S/SE; the admitted intersection is specifically
SE, never SE Plus. Its July price remains July. The September temporal gate
continues to reject it. Existing historical v3 holds remain untouched.

IDs 6, 7, 13, 17, 21 and 23 remain held for the individually recorded trim/fuel
conflicts. IDs 1, 11, 12, 18, 19, 24, 25, 26, 27 and 28 also lack a sufficiently
exact local PBEV configuration binding. The manifest records the particular
option-code, trim, powertrain, generation or unavailable-year issue for each.
No automatic alias, fuzzy matching, unapproved trim substitution or price
description alone approves a vehicle.

## Counts: never conflate price, identity, cost and readiness

| Measure | Result |
|---|---:|
| Canonical legacy vehicles reviewed | 34 |
| Hash-verified September FIPE receipts | 27 |
| Individually approved identities / PBEV bindings | 18 |
| Approved identities with September price | 17 |
| Complete academic scenario TCO (low/base/high) | 18 |
| Complete observed TCO | 0 |
| Legacy `academic_test_ready`, in any profile | 0 |
| Operational activation / recommendations | 0 / 0 |

The eighteenth calculable TCO (Ka 33) uses the actual July price and does **not**
pass the September eligibility gate. A complete scenario TCO is not observed
cost and does not override temporal, identity or profile evidence requirements.
Fuel uses existing PBEV gasoline laboratory efficiency, 1,000 km/month and the
versioned R$6/l scenario. Existing low/base/high rates are unchanged. No costs,
ratings, dimensions or safety values from the demonstration seed are copied.

No exact dimensional/capacity or safety dossier for these legacy configurations
was admitted from the registered local technical archives. Seats, body style,
dimensions (including open mirrors), wheelbase, trunk, payload, clearance,
airbags, ABS and ESC remain unavailable unless separately evidenced. Missing
equipment is never `false`. A PBEV size class is not a measured dimension, and
a similarly named model in a different-year manufacturer catalogue is not a
substitute. Individual remaining profile criteria are exposed by the replay.

The already approved 19 new vehicles are unchanged: Cidade 10, Aplicativo 19,
Trabalho 10, Espaço/capacidade 10, Família 0 and Estrada 0. The distinct ready
union is still **19/60**, leaving 41 (34 legacy plus seven not selected). Família
and Estrada each still lack ten ready options. The partial integration does not
claim this target has been achieved.

## Replay, audit and limitations

Use `legacy_matrix_v4(archive)` followed by `replay_legacy_v4(vehicles)` offline.
The latter requires all canonical IDs once and evaluates vehicles individually,
preserving mixed reference months rather than relabelling July as September.
Callers must use `academic_test_ready`, not a non-null partial preview score,
when interpreting readiness. No operational consumer is wired to this adapter.

Regression coverage includes exact scope, duplicate/missing records, version,
year, fuel, engine, transmission, invalid units/consumption, altered cache bytes,
idempotence and closed failure on missing sources. The external evidence report
contains the real-source replay, full 34-row matrix, low/base/high costs and
blockers, v3 result/byte comparisons and Git preservation checks.

This round authorizes and executes **zero** external calls. Historical planned
refreshes or estimates are not a provider balance or a new authorized budget.
There are seven prices still pending September alignment, not "seven calls
remaining". Future documentation or collection needs separate authorization;
the six unresolved original identity holds must be resolved before refreshing.
