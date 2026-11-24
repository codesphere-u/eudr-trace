"""Command-line interface for eudr-trace."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from eudr_trace.validator import (
    create_dds_evidence_bundle,
    validate_feature_collection,
    verify_dds_evidence_bundle,
)

DEMO_PLOTS = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "id": "UG-ELGON-001",
            "properties": {
                "plot_id": "UG-ELGON-001",
                "commodity": "coffee",
                "country_iso": "UG",
                "area_ha": 1.2,
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
        },
        {
            "type": "Feature",
            "id": "UG-ELGON-002",
            "properties": {
                "plot_id": "UG-ELGON-002",
                "commodity": "coffee",
                "country_iso": "UG",
                "area_ha": 0.9,
            },
            "geometry": {
                "type": "Point",
                "coordinates": [34.320456, 1.075789],
            },
        },
    ],
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="eudr-trace",
        description="Offline-first EUDR (Regulation EU 2023/1115) GeoJSON validator & DDS proof kit.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_val = sub.add_parser("validate", help="Validate a GeoJSON FeatureCollection of farmer plots")
    p_val.add_argument("geojson_file", help="Path to plots GeoJSON file")
    p_val.add_argument("--reserves", default=None, help="Optional protected reserves GeoJSON file")
    p_val.add_argument("--operator", default="Cooperative Export Union")
    p_val.add_argument("--batch-ref", default="DDS-BATCH-001")
    p_val.add_argument("--bundle-out", default=None, help="Write SHA-256 DDS evidence bundle JSON")

    p_ver = sub.add_parser("verify-bundle", help="Verify SHA-256 integrity of a DDS evidence bundle")
    p_ver.add_argument("bundle_file", help="Path to DDS evidence bundle JSON")

    sub.add_parser("demo", help="Validate a sample Mt. Elgon coffee cooperative GeoJSON batch")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "demo":
        report = validate_feature_collection(DEMO_PLOTS)
        bundle = create_dds_evidence_bundle(
            report,
            operator_name="Mt. Elgon Smallholder Coffee Cooperative",
            batch_reference="ELGON-2026-Q4",
        )
        print(json.dumps(bundle, indent=2))
        return 0 if report.passed else 2

    if args.command == "validate":
        plots_data = json.loads(Path(args.geojson_file).read_text(encoding="utf-8"))
        reserves_data = (
            json.loads(Path(args.reserves).read_text(encoding="utf-8"))
            if args.reserves
            else None
        )
        report = validate_feature_collection(plots_data, reserves_geojson=reserves_data)
        bundle = create_dds_evidence_bundle(
            report,
            operator_name=args.operator,
            batch_reference=args.batch_ref,
        )
        if args.bundle_out:
            Path(args.bundle_out).write_text(json.dumps(bundle, indent=2), encoding="utf-8")
        print(json.dumps(bundle, indent=2))
        return 0 if report.passed else 2

    if args.command == "verify-bundle":
        bundle = json.loads(Path(args.bundle_file).read_text(encoding="utf-8"))
        ok, msg = verify_dds_evidence_bundle(bundle)
        print(json.dumps({"valid": ok, "message": msg}, indent=2))
        return 0 if ok else 2

    return 1


if __name__ == "__main__":
    sys.exit(main())
