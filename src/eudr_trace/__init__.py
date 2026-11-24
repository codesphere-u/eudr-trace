"""eudr-trace — Offline-first EU Deforestation Regulation (EU 2023/1115) compliance toolkit."""

from eudr_trace.geometry import (
    WGS84_EARTH_RADIUS_M,
    decimal_places,
    point_in_ring,
    polygon_geodesic_area_hectares,
    ring_geodesic_area_sq_m,
    ring_has_self_intersection,
    ring_signed_area_2d,
    rings_overlap,
)
from eudr_trace.validator import (
    EUDR_MIN_DECIMAL_PRECISION,
    EUDR_POLYGON_THRESHOLD_HA,
    EUDR_REGULATED_COMMODITIES,
    FindingSeverity,
    PlotSummary,
    ValidationFinding,
    ValidationReport,
    create_dds_evidence_bundle,
    validate_feature_collection,
    verify_dds_evidence_bundle,
)

__version__ = "0.1.0"

__all__ = [
    "EUDR_MIN_DECIMAL_PRECISION",
    "EUDR_POLYGON_THRESHOLD_HA",
    "EUDR_REGULATED_COMMODITIES",
    "WGS84_EARTH_RADIUS_M",
    "FindingSeverity",
    "PlotSummary",
    "ValidationFinding",
    "ValidationReport",
    "__version__",
    "create_dds_evidence_bundle",
    "decimal_places",
    "point_in_ring",
    "polygon_geodesic_area_hectares",
    "ring_geodesic_area_sq_m",
    "ring_has_self_intersection",
    "ring_signed_area_2d",
    "rings_overlap",
    "validate_feature_collection",
    "verify_dds_evidence_bundle",
]
