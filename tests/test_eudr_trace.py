"""Comprehensive geodesy, EUDR Article 9 compliance, overlap, reserve, and DDS bundle tests."""

from __future__ import annotations

import json
from pathlib import Path

from eudr_trace import (
    create_dds_evidence_bundle,
    polygon_geodesic_area_hectares,
    ring_has_self_intersection,
    rings_overlap,
    validate_feature_collection,
    verify_dds_evidence_bundle,
)
from eudr_trace.cli import main as cli_main


def test_geodesic_area_near_equator_matches_known_square_degree() -> None:
    # 0.001 deg x 0.001 deg square near equator (~111.19m x 111.19m = ~1.236 ha)
    ring = [
        (34.310000, 1.070000),
        (34.311000, 1.070000),
        (34.311000, 1.071000),
        (34.310000, 1.071000),
        (34.310000, 1.070000),
    ]
    area_ha = polygon_geodesic_area_hectares([ring])
    assert 1.20 <= area_ha <= 1.27


def test_bowtie_self_intersection_and_pairwise_overlap_detection() -> None:
    bowtie = [
        (34.000001, 1.000001),
        (34.001001, 1.001001),
        (34.001001, 1.000001),
        (34.000001, 1.001001),
        (34.000001, 1.000001),
    ]
    assert ring_has_self_intersection(bowtie) is True

    sq_a = [
        (34.000001, 1.000001),
        (34.002001, 1.000001),
        (34.002001, 1.002001),
        (34.000001, 1.002001),
        (34.000001, 1.000001),
    ]
    sq_b = [
        (34.001001, 1.001001),
        (34.003001, 1.001001),
        (34.003001, 1.003001),
        (34.001001, 1.003001),
        (34.001001, 1.001001),
    ]
    sq_far = [
        (34.500001, 1.500001),
        (34.501001, 1.500001),
        (34.501001, 1.501001),
        (34.500001, 1.501001),
        (34.500001, 1.500001),
    ]
    assert rings_overlap(sq_a, sq_b) is True
    assert rings_overlap(sq_a, sq_far) is False


def test_validator_enforces_4ha_polygon_rule_precision_overlaps_and_reserves() -> None:
    plots = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"plot_id": "BIG-POINT", "commodity": "coffee", "country_iso": "UG", "area_ha": 5.5},
                "geometry": {"type": "Point", "coordinates": [34.123456, 1.234567]},
            },
            {
                "type": "Feature",
                "properties": {"plot_id": "LOW-PREC", "commodity": "cocoa", "country_iso": "GH", "area_ha": 1.0},
                "geometry": {"type": "Point", "coordinates": [-1.23, 6.45]},
            },
            {
                "type": "Feature",
                "properties": {"plot_id": "IN-PARK", "commodity": "coffee", "country_iso": "UG", "area_ha": 1.2},
                "geometry": {"type": "Point", "coordinates": [30.105123, 0.505123]},
            },
        ],
    }
    reserves = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "Protected Forest Reserve"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [30.100000, 0.500000],
                        [30.110000, 0.500000],
                        [30.110000, 0.510000],
                        [30.100000, 0.510000],
                        [30.100000, 0.500000],
                    ]],
                },
            }
        ],
    }

    report = validate_feature_collection(plots, reserves_geojson=reserves)
    assert report.passed is False
    rules = {f.rule_id for f in report.findings}
    assert {"EUDR-003", "EUDR-006", "EUDR-008"}.issubset(rules)


def test_dds_bundle_creation_tamper_verification_and_cli(tmp_path: Path) -> None:
    assert cli_main(["demo"]) == 0
    plots_file = tmp_path / "plots.geojson"
    bundle_file = tmp_path / "dds.json"
    plots_file.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {
                            "plot_id": "COOP-1",
                            "commodity": "coffee",
                            "country_iso": "UG",
                            "area_ha": 1.24,
                        },
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[
                                [34.310123, 1.070123],
                                [34.311123, 1.070123],
                                [34.311123, 1.071123],
                                [34.310123, 1.071123],
                                [34.310123, 1.070123],
                            ]],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert cli_main(["validate", str(plots_file), "--bundle-out", str(bundle_file)]) == 0
    assert cli_main(["verify-bundle", str(bundle_file)]) == 0

    bundle = json.loads(bundle_file.read_text(encoding="utf-8"))
    ok, _ = verify_dds_evidence_bundle(bundle)
    assert ok is True
    bundle["evidence"]["total_area_ha"] = 999.0
    tampered_ok, _ = verify_dds_evidence_bundle(bundle)
    assert tampered_ok is False
    # Direct API sanity check
    rep = validate_feature_collection(json.loads(plots_file.read_text(encoding="utf-8")))
    b2 = create_dds_evidence_bundle(rep, operator_name="Test Coop", batch_reference="B1")
    assert verify_dds_evidence_bundle(b2)[0] is True
