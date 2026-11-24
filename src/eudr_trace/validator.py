"""EU Deforestation Regulation (Regulation (EU) 2023/1115) Article 9 validator and DDS bundler."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from eudr_trace.geometry import (
    Point2D,
    Ring,
    decimal_places,
    point_in_ring,
    polygon_geodesic_area_hectares,
    ring_has_self_intersection,
    ring_signed_area_2d,
    rings_overlap,
)

EUDR_POLYGON_THRESHOLD_HA = 4.0
EUDR_MIN_DECIMAL_PRECISION = 6
EUDR_REGULATED_COMMODITIES = frozenset(
    {"cattle", "cocoa", "coffee", "oil_palm", "rubber", "soya", "wood"}
)


class FindingSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class ValidationFinding:
    rule_id: str
    severity: FindingSeverity
    plot_id: str
    message: str
    remediation: str


@dataclass(frozen=True)
class PlotSummary:
    plot_id: str
    geometry_type: str
    computed_area_ha: float | None
    claimed_area_ha: float | None
    commodity: str | None
    country_iso: str | None
    valid: bool
    content_sha256: str


@dataclass(frozen=True)
class ValidationReport:
    total_plots: int
    valid_plots: int
    invalid_plots: int
    total_area_ha: float
    plots: tuple[PlotSummary, ...]
    findings: tuple[ValidationFinding, ...]

    @property
    def passed(self) -> bool:
        return all(f.severity != FindingSeverity.ERROR for f in self.findings)


def _canonical_bytes(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _extract_reserve_rings(reserves_geojson: dict[str, Any] | None) -> list[tuple[str, Ring]]:
    if not reserves_geojson:
        return []
    out: list[tuple[str, Ring]] = []
    for idx, feat in enumerate(reserves_geojson.get("features", [])):
        props = feat.get("properties") or {}
        name = str(props.get("name") or props.get("id") or f"reserve-{idx + 1}")
        geom = feat.get("geometry") or {}
        gtype = geom.get("type")
        coords = geom.get("coordinates") or []
        if gtype == "Polygon" and coords:
            out.append((name, [(float(p[0]), float(p[1])) for p in coords[0]]))
        elif gtype == "MultiPolygon":
            for poly in coords:
                if poly:
                    out.append((name, [(float(p[0]), float(p[1])) for p in poly[0]]))
    return out


def validate_feature_collection(
    geojson: dict[str, Any],
    *,
    reserves_geojson: dict[str, Any] | None = None,
    min_precision: int = EUDR_MIN_DECIMAL_PRECISION,
) -> ValidationReport:
    """Validate a cooperative GeoJSON FeatureCollection against EUDR Article 9 constraints."""
    findings: list[ValidationFinding] = []
    if geojson.get("type") != "FeatureCollection" or not isinstance(geojson.get("features"), list):
        findings.append(
            ValidationFinding(
                rule_id="EUDR-001",
                severity=FindingSeverity.ERROR,
                plot_id="<collection>",
                message="Root object must be a GeoJSON FeatureCollection with a features array.",
                remediation="Export plots as an RFC 7946 GeoJSON FeatureCollection.",
            )
        )
        return ValidationReport(0, 0, 0, 0.0, (), tuple(findings))

    reserves = _extract_reserve_rings(reserves_geojson)
    valid_outer_rings: list[tuple[str, Ring]] = []
    valid_points: list[tuple[str, Point2D]] = []
    plot_summaries: list[PlotSummary] = []
    total_area_ha = 0.0

    for idx, feature in enumerate(geojson["features"]):
        props = feature.get("properties") or {}
        plot_id = str(props.get("plot_id") or feature.get("id") or f"plot-{idx + 1}")
        geom = feature.get("geometry") or {}
        gtype = str(geom.get("type") or "")
        coords = geom.get("coordinates")
        plot_errors_start = len(findings)

        commodity = props.get("commodity")
        country_iso = props.get("country_iso")
        claimed_area = props.get("area_ha")
        claimed_ha = float(claimed_area) if isinstance(claimed_area, (int, float)) else None

        if not commodity or str(commodity).lower() not in EUDR_REGULATED_COMMODITIES:
            findings.append(
                ValidationFinding(
                    rule_id="EUDR-009",
                    severity=FindingSeverity.WARNING,
                    plot_id=plot_id,
                    message=f"Missing or unrecognized EUDR commodity '{commodity}'.",
                    remediation=f"Set properties.commodity to one of: {sorted(EUDR_REGULATED_COMMODITIES)}.",
                )
            )
        if not country_iso or len(str(country_iso)) != 2:
            findings.append(
                ValidationFinding(
                    rule_id="EUDR-009",
                    severity=FindingSeverity.WARNING,
                    plot_id=plot_id,
                    message=f"Missing ISO-3166-1 alpha-2 country_iso ('{country_iso}').",
                    remediation="Include 2-letter country code (e.g. 'UG', 'KE', 'GH', 'CI').",
                )
            )

        computed_ha: float | None = None

        if gtype == "Point":
            if not isinstance(coords, list) or len(coords) < 2:
                findings.append(
                    ValidationFinding(
                        rule_id="EUDR-001",
                        severity=FindingSeverity.ERROR,
                        plot_id=plot_id,
                        message="Point geometry requires [longitude, latitude] coordinates.",
                        remediation="Supply a valid WGS84 [lon, lat] pair.",
                    )
                )
            else:
                lon, lat = float(coords[0]), float(coords[1])
                _check_coordinate(plot_id, coords[0], coords[1], min_precision, findings)
                if claimed_ha is not None and claimed_ha >= EUDR_POLYGON_THRESHOLD_HA:
                    findings.append(
                        ValidationFinding(
                            rule_id="EUDR-006",
                            severity=FindingSeverity.ERROR,
                            plot_id=plot_id,
                            message=(
                                f"Plot area ({claimed_ha:.2f} ha) is >= {EUDR_POLYGON_THRESHOLD_HA} ha "
                                "and legally requires a Polygon under EUDR Article 9(1)(d)."
                            ),
                            remediation="Trace the full plot perimeter polygon with GPS instead of a single point.",
                        )
                    )
                valid_points.append((plot_id, (lon, lat)))
                if claimed_ha is not None:
                    total_area_ha += claimed_ha

        elif gtype in ("Polygon", "MultiPolygon"):
            raw_polys = [coords] if gtype == "Polygon" else (coords or [])
            poly_area_sum = 0.0
            for raw_poly in raw_polys:
                if not isinstance(raw_poly, list) or not raw_poly:
                    findings.append(
                        ValidationFinding(
                            rule_id="EUDR-004",
                            severity=FindingSeverity.ERROR,
                            plot_id=plot_id,
                            message="Polygon has no linear rings.",
                            remediation="Include at least one closed exterior linear ring (>=4 vertices).",
                        )
                    )
                    continue
                parsed_rings: list[Ring] = []
                ring_ok = True
                for r_idx, raw_ring in enumerate(raw_poly):
                    if not isinstance(raw_ring, list) or len(raw_ring) < 4:
                        findings.append(
                            ValidationFinding(
                                rule_id="EUDR-004",
                                severity=FindingSeverity.ERROR,
                                plot_id=plot_id,
                                message=f"Linear ring {r_idx} has fewer than 4 coordinate pairs.",
                                remediation="Provide at least 3 distinct vertices plus a closing vertex.",
                            )
                        )
                        ring_ok = False
                        continue
                    ring: Ring = []
                    for pt in raw_ring:
                        lon, lat = float(pt[0]), float(pt[1])
                        _check_coordinate(plot_id, pt[0], pt[1], min_precision, findings)
                        ring.append((lon, lat))
                    if ring[0] != ring[-1]:
                        findings.append(
                            ValidationFinding(
                                rule_id="EUDR-004",
                                severity=FindingSeverity.ERROR,
                                plot_id=plot_id,
                                message=f"Linear ring {r_idx} is not closed (first vertex != last vertex).",
                                remediation="Repeat the opening coordinate as the final coordinate.",
                            )
                        )
                        ring_ok = False
                    if ring_has_self_intersection(ring):
                        findings.append(
                            ValidationFinding(
                                rule_id="EUDR-005",
                                severity=FindingSeverity.ERROR,
                                plot_id=plot_id,
                                message=f"Linear ring {r_idx} contains a self-intersection (bowtie geometry).",
                                remediation="Clean crossed GPS track vertices before submitting to EU TRACES.",
                            )
                        )
                        ring_ok = False
                    if r_idx == 0 and ring_signed_area_2d(ring) < 0:
                        findings.append(
                            ValidationFinding(
                                rule_id="EUDR-004",
                                severity=FindingSeverity.WARNING,
                                plot_id=plot_id,
                                message="Exterior ring is clockwise; RFC 7946 recommends counter-clockwise winding.",
                                remediation="Reverse exterior ring vertex order to follow RFC 7946 right-hand rule.",
                            )
                        )
                    parsed_rings.append(ring)

                if ring_ok and parsed_rings:
                    poly_area_sum += polygon_geodesic_area_hectares(parsed_rings)
                    valid_outer_rings.append((plot_id, parsed_rings[0]))

            computed_ha = round(poly_area_sum, 4)
            total_area_ha += computed_ha
            if claimed_ha is not None and claimed_ha > 0 and computed_ha > 0:
                rel_diff = abs(computed_ha - claimed_ha) / max(claimed_ha, computed_ha)
                if rel_diff > 0.25:
                    findings.append(
                        ValidationFinding(
                            rule_id="EUDR-006",
                            severity=FindingSeverity.WARNING,
                            plot_id=plot_id,
                            message=(
                                f"Geodesic polygon area ({computed_ha:.2f} ha) differs by "
                                f"{rel_diff * 100:.0f}% from claimed area ({claimed_ha:.2f} ha)."
                            ),
                            remediation="Verify GPS perimeter capture against farmer land record.",
                        )
                    )
        else:
            findings.append(
                ValidationFinding(
                    rule_id="EUDR-001",
                    severity=FindingSeverity.ERROR,
                    plot_id=plot_id,
                    message=f"Unsupported geometry type '{gtype}' (EUDR allows Point, Polygon, MultiPolygon).",
                    remediation="Convert geometry to WGS84 Point (<4 ha) or Polygon (>=4 ha).",
                )
            )

        plot_has_error = any(
            f.severity == FindingSeverity.ERROR for f in findings[plot_errors_start:]
        )
        plot_summaries.append(
            PlotSummary(
                plot_id=plot_id,
                geometry_type=gtype,
                computed_area_ha=computed_ha,
                claimed_area_ha=claimed_ha,
                commodity=str(commodity) if commodity else None,
                country_iso=str(country_iso).upper() if country_iso else None,
                valid=not plot_has_error,
                content_sha256=hashlib.sha256(_canonical_bytes(feature)).hexdigest(),
            )
        )

    # Pairwise cooperative overlap detection
    overlapped_ids: set[str] = set()
    for i in range(len(valid_outer_rings)):
        pid_a, ring_a = valid_outer_rings[i]
        for j in range(i + 1, len(valid_outer_rings)):
            pid_b, ring_b = valid_outer_rings[j]
            if pid_a != pid_b and rings_overlap(ring_a, ring_b):
                overlapped_ids.update((pid_a, pid_b))
                findings.append(
                    ValidationFinding(
                        rule_id="EUDR-007",
                        severity=FindingSeverity.ERROR,
                        plot_id=pid_a,
                        message=f"Plot '{pid_a}' spatially overlaps cooperative plot '{pid_b}'.",
                        remediation="Resolve boundary GPS drift or duplicate farmer registration before export.",
                    )
                )

    # Protected forest / conservation reserve encroachment check
    encroached_ids: set[str] = set()
    for r_name, r_ring in reserves:
        for pid, pt in valid_points:
            if point_in_ring(pt, r_ring):
                encroached_ids.add(pid)
                findings.append(
                    ValidationFinding(
                        rule_id="EUDR-008",
                        severity=FindingSeverity.ERROR,
                        plot_id=pid,
                        message=f"Plot point '{pid}' falls inside protected reserve '{r_name}'.",
                        remediation="Quarantine lot and conduct ground-truth legal boundary verification.",
                    )
                )
        for pid, p_ring in valid_outer_rings:
            if rings_overlap(p_ring, r_ring):
                encroached_ids.add(pid)
                findings.append(
                    ValidationFinding(
                        rule_id="EUDR-008",
                        severity=FindingSeverity.ERROR,
                        plot_id=pid,
                        message=f"Plot polygon '{pid}' encroaches on protected reserve '{r_name}'.",
                        remediation="Exclude encroaching parcel from EU-bound shipment and verify land title.",
                    )
                )

    flagged = overlapped_ids | encroached_ids
    final_summaries = tuple(
        PlotSummary(
            plot_id=s.plot_id,
            geometry_type=s.geometry_type,
            computed_area_ha=s.computed_area_ha,
            claimed_area_ha=s.claimed_area_ha,
            commodity=s.commodity,
            country_iso=s.country_iso,
            valid=s.valid and (s.plot_id not in flagged),
            content_sha256=s.content_sha256,
        )
        for s in plot_summaries
    )
    valid_count = sum(1 for s in final_summaries if s.valid)
    return ValidationReport(
        total_plots=len(final_summaries),
        valid_plots=valid_count,
        invalid_plots=len(final_summaries) - valid_count,
        total_area_ha=round(total_area_ha, 4),
        plots=final_summaries,
        findings=tuple(findings),
    )


def _check_coordinate(
    plot_id: str,
    raw_lon: Any,
    raw_lat: Any,
    min_precision: int,
    findings: list[ValidationFinding],
) -> None:
    lon, lat = float(raw_lon), float(raw_lat)
    if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
        findings.append(
            ValidationFinding(
                rule_id="EUDR-002",
                severity=FindingSeverity.ERROR,
                plot_id=plot_id,
                message=f"Coordinate [{lon}, {lat}] is outside valid WGS84 bounds.",
                remediation="Ensure coordinates are [longitude, latitude] in WGS84 (EPSG:4326).",
            )
        )
    if abs(lon) < 1e-9 and abs(lat) < 1e-9:
        findings.append(
            ValidationFinding(
                rule_id="EUDR-002",
                severity=FindingSeverity.ERROR,
                plot_id=plot_id,
                message="Coordinate is (0, 0) Null Island (GPS fix failure).",
                remediation="Re-capture plot geolocation with an active GPS lock.",
            )
        )
    if (
        (decimal_places(raw_lon) < min_precision or decimal_places(raw_lat) < min_precision)
        and not any(f.plot_id == plot_id and f.rule_id == "EUDR-003" for f in findings)
    ):
        findings.append(
            ValidationFinding(
                rule_id="EUDR-003",
                severity=FindingSeverity.ERROR,
                plot_id=plot_id,
                message=(
                    f"Coordinate [{raw_lon}, {raw_lat}] has fewer than {min_precision} "
                    "decimal places required by EU TRACES NT."
                ),
                remediation=f"Record coordinates with at least {min_precision} decimal places (~0.11m).",
            )
        )


def create_dds_evidence_bundle(
    report: ValidationReport,
    *,
    operator_name: str,
    batch_reference: str,
) -> dict[str, Any]:
    """Build a canonical, SHA-256 tamper-evident Due Diligence Statement (DDS) proof bundle."""
    body = {
        "schema": "eudr-trace/dds-evidence/v1",
        "regulation": "Regulation (EU) 2023/1115",
        "generated_at": datetime.now(UTC).isoformat(),
        "operator_name": operator_name,
        "batch_reference": batch_reference,
        "passed": report.passed,
        "total_plots": report.total_plots,
        "valid_plots": report.valid_plots,
        "invalid_plots": report.invalid_plots,
        "total_area_ha": report.total_area_ha,
        "plots": [
            {
                "plot_id": p.plot_id,
                "geometry_type": p.geometry_type,
                "computed_area_ha": p.computed_area_ha,
                "claimed_area_ha": p.claimed_area_ha,
                "commodity": p.commodity,
                "country_iso": p.country_iso,
                "valid": p.valid,
                "content_sha256": p.content_sha256,
            }
            for p in report.plots
        ],
        "findings": [
            {
                "rule_id": f.rule_id,
                "severity": f.severity.value,
                "plot_id": f.plot_id,
                "message": f.message,
            }
            for f in report.findings
        ],
    }
    bundle_sha256 = hashlib.sha256(_canonical_bytes(body)).hexdigest()
    return {"bundle_sha256": bundle_sha256, "evidence": body}


def verify_dds_evidence_bundle(bundle: dict[str, Any]) -> tuple[bool, str]:
    """Verify cryptographic SHA-256 integrity of a DDS evidence bundle."""
    expected = str(bundle.get("bundle_sha256", ""))
    evidence = bundle.get("evidence")
    if not expected or not isinstance(evidence, dict):
        return False, "Missing bundle_sha256 or evidence object"
    computed = hashlib.sha256(_canonical_bytes(evidence)).hexdigest()
    if computed != expected:
        return False, "Bundle SHA-256 mismatch (evidence was modified)"
    return True, "DDS evidence bundle integrity verified"
