# eudr-trace

**Offline-first EU Deforestation Regulation (Regulation (EU) 2023/1115) smallholder GeoJSON validator, spherical geodesic area & overlap/reserve encroachment checker, and SHA-256 Due Diligence Statement (DDS) proof kit.**

Zero runtime dependencies (no GDAL/GEOS/Shapely C binaries required). Pure Python 3.11+. Designed for coffee, cocoa, rubber, soya, palm-oil, and timber smallholder cooperatives across Africa, Latin America, and Southeast Asia.

## Why `eudr-trace` Exists

Under Regulation (EU) 2023/1115 Article 9, every EU-bound shipment of regulated agricultural commodities requires validated WGS84 plot geolocations:
- **6+ decimal places** coordinate precision (~0.11m) for EU TRACES NT ingestion.
- **Full closed polygons** (not points) for every plot `>= 4.0` hectares.
- **Zero self-intersections, null-island GPS glitches, duplicate overlapping cooperative claims, or protected forest reserve encroachments.**

Commercial EUDR SaaS platforms charge per-hectare or per-farmer fees smallholders cannot afford and fail completely offline. `eudr-trace` runs locally on any laptop or field server with zero network dependency.

## Quick Start

```bash
uv sync --extra dev
eudr-trace demo
eudr-trace validate plots.geojson --reserves protected_forests.geojson --bundle-out dds-evidence.json
eudr-trace verify-bundle dds-evidence.json
```

## License

MIT License — see [LICENSE](LICENSE).
