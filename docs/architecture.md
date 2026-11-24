# Architecture — `eudr-trace`

1. **`eudr_trace.geometry`** — Pure-Python WGS84 Chamberlain-Duquette spherical geodesic area calculation (in m² and hectares), exact decimal-place counting via `Decimal`, 2D orientation-predicate segment intersection for bowtie self-intersection detection, ray-casting point-in-polygon, and bounding-box prefiltered polygon overlap checks.
2. **`eudr_trace.validator`** — Enforces Regulation (EU) 2023/1115 Article 9 rules (`EUDR-001`..`EUDR-009`), pairwise cooperative plot overlap detection, local protected-reserve encroachment checking, and canonical SHA-256 Due Diligence Statement (DDS) evidence bundle creation & verification.
3. **`eudr_trace.cli`** — Offline CLI for batch validation, DDS bundle export, cryptographic verification, and demo execution.
