# Batch 4: six opt-in academic admissions

This additive module reuses the existing v4 methodology, FIPE/PBEV crosswalks,
scenario rates and CarPedia parser/normalizer. It never invokes HTTP, a database,
publication, production APIs or frontend ranking. Existing v3 and Batch 1–3
files are unchanged.

## Scope and identity

Admitted reserved IDs: 44 Fiesta SE 1.6 manual 2018; 45 Rio EX 1.6 automatic
2021; 51 Grand Siena Attractive 1.0 manual 2020; 52 Arrizo 5 RXT CVT 2020;
54 Cerato EX 2.0 automatic 2020; 56 Arrizo 6 GSX CVT 2021.
The human approvals for Rio EX and Arrizo GSX remain mandatory. These are not
silent substitutions for the originally proposed LX and Pro versions.

Each ficha uses the exact FIPE numeric identifier, commercial description and
year. Fuel must be explicitly Flex. Manual and conventional automatic require
an explicit gear count consistent with PBEV; generic automatic cannot prove
CVT. PBEV shared rows for Fiesta SE/SEL and Cerato EX/LX/SX/GT apply only to the
reviewed common powertrain, not trim equipment. The exact trim is independently
identified by the FIPE-bound ficha. No fuzzy match is used.

## Provenance and precedence

`batch4_evidence_v1.json` pins the crosswalk fingerprint, complete response hash,
timestamp, upstream source, exact source identity and every admitted JSON field
locator/value/unit. The six source responses stay outside Git. FIPE prices are
September 2026; PBEV provides consumption, fuel and transmission. CarPedia only
supplies explicit seats, body dimensions, payload and cargo capacity. Its
consumption and prices never replace official observations. Litres `L` map
explicitly to the profile unit `l` without changing the numerical value.

Fiesta seats are now explicitly stated as five by its exact 2018 ficha, not
inferred from headrests, belts or pictures. No new OEM receipt is asserted.
Previously described Ford safety equipment is not imported from a user summary
without a hash-bound document. All six new safety inventories remain unknown;
no missing equipment is converted into false. Body width is not mirror width.

The CarPedia upstream source is recorded as `checktudo-ficha-tecnica-2026-07`,
dated 2026-07-13. These are attributed technical source assertions, not newly
measured physical dimensions. Unselected attributes are not independently
validated or promoted. The habitability proxy remains explicitly academic.

## Rejections and totals

35 Kwid remains blocked by the unresolved 3679/3680 mm source conflict; no gate
is relaxed even for profiles which do not directly consume length.
40 Picanto GT remains blocked for this round: PBEV EX5/LX5 alone does not prove
the exact GT trim. 41 QQ remains pending a human year decision with its fuel
contradiction preserved. These candidates remain versioned, inactive backlog.

The composition is 34 legacy + 26 new = 60 identities. Only 43 are academically
testable: 17 legacy + 26 new. The remaining 17 legacy vehicles are not silently
promoted. Completing composition is not achieving 60/60 readiness.

Six HTTP ficha requests succeeded, no retries. Inherited balances: CarPedia
15 to 9, FIPE 18 unchanged, public document downloads 32 unchanged. Three
targeted web discovery queries were recorded separately; no new documentary
download or safety evidence was admitted. No quota was reset.

## Validation

Replay each vehicle and all scenarios, then remove/reinsert logically and
replay the combined cohort. Reject duplicate IDs/canonical bindings, changed
raw bytes, missing seats, invalid units, version/year/fuel/gear differences,
pending human decisions and source conflicts. Compare the prior 37 results and
v3 fingerprints without changing their bytes. `academic_test_ready` never
implies observed TCO, operational activation or recommendation.
