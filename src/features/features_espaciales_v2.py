"""Audit fixed colony geometry and build causal spatial V2 context.

Run with: python -B -m src.features.features_espaciales_v2
No legacy writes, repairs, station reassignment, fitting or distance fallback.
Queen topology is tested in the source representation; all measurements use UTM.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import subprocess
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np
import pandas as pd
import pyproj
import shapely
from pyproj import CRS, Transformer
from shapely.geometry import Point, shape
from shapely.ops import transform
from shapely.validation import explain_validity

from src.data.ecobici_v2 import build_catalog, load_stations, sha256_file

ROOT = Path(__file__).resolve().parents[2]
VERSION = '2.0-phase3-spatial'
ANALYSIS_CRS = 'EPSG:32614'
EXPORT_CRS = 'EPSG:4326'
KEY = ['zone_id', 'periodo']
DYNAMIC = ['neighbor_trips_lag1', 'neighbor_growth_lag1', 'neighbor_trips_mean_lag3',
           'neighbor_active_zones', 'neighbor_observation_coverage']
STATIC = ['n_estaciones_colonia_catalogo', 'estaciones_por_km2_catalogo',
          'neighbor_station_count_catalogo', 'neighbor_station_density_catalogo']
CAUSAL = ['n_neighbors_queen'] + DYNAMIC
OUTPUTS = ['geospatial_audit_v2.csv', 'zone_neighbors_v2.csv',
           'geospatial_overlaps_v2.csv', 'zonas_sin_geometria_v2.csv',
           'stations_geometry_audit_v2.csv', 'features_espaciales_v2.csv',
           'features_temporal_spatial_v2.csv', 'geospatial_audit_v2.metadata.json',
           'features_espaciales_v2.metadata.json']


def validate_catalog(catalog):
    if catalog.zone_id.isna().any() or catalog.zone_id.duplicated().any():
        raise ValueError('Catalog zone_id must be non-null and unique')
    lookup = {}
    for r in catalog.itertuples():
        for label in set(json.loads(r.aliases) + [r.colonia]):
            key = (r.alcaldia, label)
            if key in lookup and lookup[key] != r.zone_id:
                raise ValueError('Ambiguous curated alias')
            lookup[key] = r.zone_id
    return lookup


def metric_transformer(source_crs, analysis_crs=ANALYSIS_CRS):
    crs = CRS.from_user_input(analysis_crs)
    if not crs.is_projected or any(a.unit_name != 'metre' for a in crs.axis_info):
        raise ValueError('Areas and distances require a projected CRS in metres')
    return Transformer.from_crs(source_crs, crs, always_xy=True)


def audit_geometry(catalog, geojson, analysis_crs=ANALYSIS_CRS):
    lookup = validate_catalog(catalog)
    source_crs = geojson.get('crs', {}).get('properties', {}).get('name', 'OGC:CRS84')
    crs = CRS.from_user_input(source_crs)
    projector = metric_transformer(crs, analysis_crs)
    reverse = Transformer.from_crs(analysis_crs, EXPORT_CRS, always_xy=True)
    source, projected, details, extras = {}, {}, {}, []
    for index, feature in enumerate(geojson['features']):
        prop = feature.get('properties') or {}
        zone = lookup.get((prop.get('alcaldia'), prop.get('colonia')))
        if zone is None:
            extras.append({'feature_index': index, 'properties': prop})
            continue
        if zone in details:
            raise ValueError('Multiple geometries resolve to one zone_id')
        raw = feature.get('geometry')
        geom = shape(raw) if raw else None
        valid = geom is not None and not geom.is_empty and geom.is_valid
        polygon = geom is not None and geom.geom_type in ('Polygon', 'MultiPolygon')
        reason = 'null_geometry' if geom is None else explain_validity(geom)
        eligible = valid and polygon
        projected_geom = transform(projector.transform, geom) if eligible else None
        if eligible and (not projected_geom.is_valid or projected_geom.is_empty or projected_geom.area <= 0):
            eligible = False
            reason = 'invalid_after_projection: ' + explain_validity(projected_geom)
        details[zone] = {'geometry_available': geom is not None and not geom.is_empty,
                         'geometry_valid': bool(valid), 'geometry_type': geom.geom_type if geom is not None else None,
                         'geometry_usable': bool(eligible), 'validity_error': None if eligible else reason,
                         'repairability': 'not_needed' if eligible else 'not_assessed',
                         'repair_method_proposed': None if eligible else 'manual review; assess make_valid without overwriting source',
                         'geometry_repaired': False}
        if eligible:
            source[zone], projected[zone] = geom, projected_geom
    edges, overlaps = [], []
    for a, b in itertools.combinations(sorted(source), 2):
        # No snapping/buffering. Projection can perturb a shared straight segment.
        if source[a].touches(source[b]):
            distance = projected[a].centroid.distance(projected[b].centroid)
            for i, j in [(a, b), (b, a)]:
                edges.append({'zone_id': i, 'neighbor_zone_id': j, 'relation_type': 'queen',
                              'distance_centroid_m': distance, 'weight_raw': 1.0})
        intersection = source[a].intersection(source[b])
        area = transform(projector.transform, intersection).area
        if area > 0:
            overlaps.append({'zone_id': a, 'other_zone_id': b, 'overlap_area_m2': area,
                             'overlap_gt_1m2': area > 1, 'action': 'reported_not_repaired'})
    neighbors = pd.DataFrame(edges, columns=['zone_id', 'neighbor_zone_id', 'relation_type',
                                             'distance_centroid_m', 'weight_raw'])
    neighbors['weight_normalized'] = neighbors.weight_raw / neighbors.groupby('zone_id').weight_raw.transform('sum')
    overlap_frame = pd.DataFrame(overlaps, columns=['zone_id', 'other_zone_id', 'overlap_area_m2', 'overlap_gt_1m2', 'action'])
    rows = []
    for r in catalog.sort_values('zone_id').itertuples():
        d = details.get(r.zone_id, {'geometry_available': False, 'geometry_valid': None,
                                   'geometry_type': None, 'geometry_usable': False, 'validity_error': None,
                                   'repairability': 'missing_source', 'repair_method_proposed': None, 'geometry_repaired': False})
        poly = projected.get(r.zone_id)
        x = y = lon = lat = area = np.nan
        if poly is not None:
            x, y, area = poly.centroid.x, poly.centroid.y, poly.area
            lon, lat = reverse.transform(x, y)
        n = int(neighbors.zone_id.eq(r.zone_id).sum())
        ov = sum(1 for row in overlaps if r.zone_id in (row['zone_id'], row['other_zone_id']))
        notes = []
        if not d['geometry_available']: notes.append('no_polygon_match')
        elif not d['geometry_usable']: notes.append('unusable_geometry')
        elif n == 0: notes.append('queen_isolate_no_fallback')
        if ov: notes.append('positive_area_intersections_reported')
        rows.append({'zone_id': r.zone_id, 'colonia': r.colonia, 'alcaldia': r.alcaldia, **d,
                     'source_crs': crs.to_string(), 'analysis_crs': CRS.from_user_input(analysis_crs).to_string(),
                     'export_crs': EXPORT_CRS, 'area_m2': area, 'area_km2': area / 1e6,
                     'centroid_x': x, 'centroid_y': y, 'centroid_lon': lon, 'centroid_lat': lat,
                     'n_neighbors_queen': n if poly is not None else np.nan,
                     'n_neighbors_distance': 0 if poly is not None else np.nan,
                     'n_overlap_pairs': ov, 'notes': ';'.join(notes)})
    audit = pd.DataFrame(rows)
    info = {'source_crs': crs.to_string(), 'analysis_crs': CRS.from_user_input(analysis_crs).to_string(),
            'export_crs': EXPORT_CRS, 'source_crs_inferred': 'crs' not in geojson,
            'n_geojson_features': len(geojson['features']), 'unmatched_geojson_features': extras,
            'n_invalid_geometries': sum(d['geometry_available'] and not d['geometry_valid'] for d in details.values()),
            'n_null_geometries': sum(not d['geometry_available'] for d in details.values()),
            'n_multipart': int(audit.geometry_type.eq('MultiPolygon').sum()),
            'n_overlap_pairs': len(overlaps), 'n_overlap_pairs_gt_1m2': sum(r['overlap_gt_1m2'] for r in overlaps),
            'max_overlap_m2': max([r['overlap_area_m2'] for r in overlaps], default=0),
            'geometry_repairs': [], 'topology_reference': 'source coordinates; no snapping or buffering'}
    return audit, neighbors, overlap_frame, projected, info


def validate_neighbors(neighbors, zone_ids):
    if neighbors.duplicated(['zone_id', 'neighbor_zone_id']).any():
        raise ValueError('Duplicate neighbor pair')
    if neighbors.zone_id.eq(neighbors.neighbor_zone_id).any():
        raise ValueError('Self neighbor')
    if not set(neighbors.zone_id).union(neighbors.neighbor_zone_id) <= set(zone_ids):
        raise ValueError('Unknown graph zone_id')
    if not neighbors.relation_type.eq('queen').all():
        raise ValueError('This run supports Queen only; no mixed fallback')
    expected = neighbors.weight_raw / neighbors.groupby('zone_id').weight_raw.transform('sum')
    if (not np.allclose(neighbors.weight_raw, 1)
            or not np.allclose(neighbors.weight_normalized, expected)
            or not np.allclose(neighbors.groupby('zone_id').weight_normalized.sum(), 1)):
        raise ValueError('Invalid weights')
    if not np.isfinite(neighbors[['weight_raw', 'weight_normalized', 'distance_centroid_m']]).all().all():
        raise ValueError('Nonfinite edge measurement')
    if (neighbors.distance_centroid_m < 0).any():
        raise ValueError('Negative metric distance')


def combine_features(temporal, spatial):
    for frame in [temporal, spatial]:
        if frame[KEY].isna().any().any() or frame.duplicated(KEY).any():
            raise ValueError('Duplicate or null zone/month key; many-to-many forbidden')
    if set(map(tuple, temporal[KEY].to_numpy())) != set(map(tuple, spatial[KEY].to_numpy())):
        raise ValueError('Temporal and spatial key universes differ')
    if set(temporal.columns).intersection(spatial.columns) - set(KEY):
        raise ValueError('Ambiguous non-key columns')
    return temporal.merge(spatial, on=KEY, how='left', validate='one_to_one')


def causal_spatial_features(frame):
    """Explicit allowlist: descriptive snapshots never become training inputs."""
    return frame[KEY + CAUSAL].copy()


def build_spatial_features(panel, catalog, audit, neighbors):
    validate_catalog(catalog)
    validate_neighbors(neighbors, catalog.zone_id)
    if panel[KEY].isna().any().any() or panel.duplicated(KEY).any():
        raise ValueError('Panel key must be unique and non-null')
    if set(panel.zone_id) != set(catalog.zone_id):
        raise ValueError('Panel/catalog zone universes differ')
    if audit.zone_id.duplicated().any() or set(audit.zone_id) != set(catalog.zone_id):
        raise ValueError('Audit/catalog zone universes differ')
    data = panel.copy()
    data['periodo'] = pd.PeriodIndex(data.periodo, freq='M')
    data['viajes_total'] = pd.to_numeric(data.viajes_total, errors='raise').where(
        data.data_status.isin(['OBSERVED', 'ZERO_DEMAND']))
    if (data.viajes_total.dropna() < 0).any() or np.isinf(data.viajes_total.dropna()).any():
        raise ValueError('Invalid activity values')
    target = data.set_index(KEY).viajes_total
    earliest = pd.to_datetime(data['target_available_no_earlier_than']) if 'target_available_no_earlier_than' in data else pd.Series(pd.NaT, index=data.index)
    data['earliest'] = earliest
    available = data.set_index(KEY).earliest
    audit_idx, cat_idx = audit.set_index('zone_id'), catalog.set_index('zone_id')
    rows = []
    for zone, group in data.groupby('zone_id', sort=True):
        node = audit_idx.loc[zone]
        edge = neighbors[neighbors.zone_id.eq(zone)]
        ids, weights = edge.neighbor_zone_id.tolist(), edge.weight_normalized.to_numpy()
        for period in sorted(group.periodo):
            def observed(k):
                keys = pd.MultiIndex.from_tuples([(j, period - k) for j in ids], names=KEY)
                values = target.reindex(keys).to_numpy(dtype=float)
                dates = available.reindex(keys)
                # Earliest known availability is a lower bound, not publication certification.
                late = dates.notna().to_numpy() & (dates > period.to_timestamp()).to_numpy()
                values[late] = np.nan
                return values
            def weighted(values):
                values = np.asarray(values, dtype=float)
                valid = np.isfinite(values)
                return float(np.dot(weights[valid], values[valid]) / weights[valid].sum()) if valid.any() else np.nan
            lag1, lag2, lag3 = (observed(k) for k in (1, 2, 3))
            growth = np.divide(lag1 - lag2, np.abs(lag2), out=np.full(len(ids), np.nan), where=np.isfinite(lag2) & (lag2 != 0))
            mean3 = (lag1 + lag2 + lag3) / 3
            counts = cat_idx.loc[ids, 'n_estaciones_catalogo_actual'].to_numpy(dtype=float)
            densities = counts / audit_idx.loc[ids, 'area_km2'].to_numpy(dtype=float)
            valid = np.isfinite(lag1)
            rows.append({'zone_id': zone, 'periodo': str(period), 'n_neighbors_queen': node.n_neighbors_queen,
                         'neighbor_trips_lag1': weighted(lag1), 'neighbor_growth_lag1': weighted(growth),
                         'neighbor_trips_mean_lag3': weighted(mean3),
                         'neighbor_active_zones': int(valid.sum()) if len(ids) else np.nan,
                         'neighbor_observation_coverage': float(weights[valid].sum()) if len(ids) else np.nan,
                         'neighbor_growth_coverage': float(weights[np.isfinite(growth)].sum()) if len(ids) else np.nan,
                         'neighbor_mean3_coverage': float(weights[np.isfinite(mean3)].sum()) if len(ids) else np.nan,
                         'spatial_features_available': bool(len(ids) and valid.any()),
                         'spatial_geometry_usable': bool(node.geometry_usable),
                         'n_estaciones_colonia_catalogo': cat_idx.loc[zone, 'n_estaciones_catalogo_actual'],
                         'estaciones_por_km2_catalogo': cat_idx.loc[zone, 'n_estaciones_catalogo_actual'] / node.area_km2,
                         'neighbor_station_count_catalogo': float(counts.sum()) if len(ids) else np.nan,
                         'neighbor_station_density_catalogo': weighted(densities),
                         'station_snapshot_type': 'STATIC_CURRENT_SNAPSHOT',
                         'station_snapshot_historical_safe': False})
    return pd.DataFrame(rows)


def station_geometry_audit(stations, projected):
    projector = metric_transformer(EXPORT_CRS)
    rows = []
    for r in stations.sort_values('num_cicloe').itertuples():
        point = Point(*projector.transform(r.longitud, r.latitud))
        candidates = sorted(zone for zone, poly in projected.items() if poly.covers(point))
        poly = projected.get(r.zone_id)
        nearest = min(projected, key=lambda zone: (point.distance(projected[zone]), zone)) if projected else None
        rows.append({'station_id': r.num_cicloe, 'zone_id_catalog': r.zone_id,
                     'zone_id_spatial': candidates[0] if len(candidates) == 1 else None,
                     'inside_catalog_polygon': poly.covers(point) if poly is not None else None,
                     'distance_to_catalog_polygon_m': point.distance(poly) if poly is not None else np.nan,
                     'possible_zone_candidate': json.dumps(candidates if candidates else ([nearest] if nearest else [])),
                     'candidate_basis': 'covers' if candidates else 'nearest_available_polygon_not_assignment',
                     'n_covering_polygons': len(candidates),
                     'status': 'missing_catalog_polygon' if poly is None else ('inside' if poly.covers(point) else 'outside'),
                     'assignment_changed': False})
    return pd.DataFrame(rows)


def missing_geometry_report(catalog, audit, panel, crosswalk):
    missing = audit.loc[~audit.geometry_available, 'zone_id']
    totals = panel.groupby('zone_id').viajes_total.sum(min_count=1)
    rows = []
    for r in catalog[catalog.zone_id.isin(missing)].itertuples():
        aliases = json.loads(r.aliases)
        candidates = crosswalk[(crosswalk.alcaldia == r.alcaldia) & crosswalk.colonia_ecobici.isin(aliases)]
        exact = sorted(candidates.colonias_cdmx_nomut.dropna().unique())
        suggestions = []
        for other in audit[(audit.alcaldia == r.alcaldia) & audit.geometry_available].itertuples():
            score = SequenceMatcher(None, r.colonia.casefold(), other.colonia.casefold()).ratio()
            if score >= 0.6:
                suggestions.append({'zone_id': other.zone_id, 'colonia': other.colonia, 'similarity': round(score, 3)})
        suggestions.sort(key=lambda x: (-x['similarity'], x['zone_id']))
        rows.append({'zone_id': r.zone_id, 'colonia': r.colonia, 'alcaldia': r.alcaldia,
                     'n_estaciones': r.n_estaciones_catalogo_actual,
                     'viajes_total_acumulados': totals.get(r.zone_id, np.nan),
                     'possible_alias': json.dumps([a for a in aliases if a != r.colonia], ensure_ascii=False),
                     'possible_match': json.dumps({'crosswalk_labels': exact, 'name_candidates': suggestions[:3]}, ensure_ascii=False),
                     'reason_unmatched': 'no_exact_polygon_in_existing_geojson; candidates_unverified_no_merge'})
    return pd.DataFrame(rows, columns=['zone_id', 'colonia', 'alcaldia', 'n_estaciones', 'viajes_total_acumulados', 'possible_alias', 'possible_match', 'reason_unmatched'])


def feature_registry():
    descriptions = {
        'n_neighbors_queen': ('Fixed-graph Queen degree', 'fixed geometry'),
        'neighbor_trips_lag1': ('Valid-neighbor weighted mean of station endpoints', 't-1'),
        'neighbor_growth_lag1': ('Weighted mean of (y[t-1]-y[t-2])/abs(y[t-2]); nonzero denominator', 't-2 through t-1'),
        'neighbor_trips_mean_lag3': ('Weighted mean of complete three-month neighbor means', 't-3 through t-1'),
        'neighbor_active_zones': ('Count of neighbors with valid available activity, including observed zero', 't-1'),
        'neighbor_observation_coverage': ('Fraction of Queen weights with usable lag1', 't-1'),
        'neighbor_growth_coverage': ('Fraction of Queen weights with usable growth', 't-2 through t-1'),
        'neighbor_mean3_coverage': ('Fraction of Queen weights with usable three-month mean', 't-3 through t-1'),
    }
    rows = [{'name': name, 'description': desc, 'historical_safe': True,
             'source': 'panel_demanda_v2.csv + fixed Queen graph', 'temporal_reference': ref,
             'qualification': 'event-time causal; earliest-availability guard applied; publication vintage unverified'}
            for name, (desc, ref) in descriptions.items()]
    static_desc = ['Current catalog stations assigned to colony', 'Current assigned stations / projected area_km2',
                   'Sum of current station counts in Queen neighbors', 'Queen-weighted mean of neighbor stations / neighbor area_km2']
    rows += [{'name': name, 'description': desc, 'historical_safe': False,
              'source': 'Caracteristicas_estaciones.csv + fixed geometry',
              'temporal_reference': 'STATIC_CURRENT_SNAPSHOT', 'default_model_feature': False}
             for name, desc in zip(STATIC, static_desc)]
    return rows


def main():
    processed = ROOT / 'data/processed'
    sources = [processed / name for name in ['panel_demanda_v2.csv', 'panel_demanda_v2.metadata.json',
               'features_temporales_v2.csv', 'catalogo_zonas_v2.csv', 'zonas_geometria.geojson', 'crosswalk_colonias.csv']]
    sources += [ROOT / 'data/raw/ecobici/Caracteristicas_estaciones.csv', ROOT / 'config/aliases_colonias_v2.json',
                ROOT / 'src/data/ecobici_v2.py', ROOT / 'requirements-spatial-v2.txt', Path(__file__)]
    fingerprints = {str(p.relative_to(ROOT)): sha256_file(p) for p in sources}
    protected = {str(p.relative_to(ROOT)): sha256_file(p) for p in processed.rglob('*') if p.is_file() and p.name not in OUTPUTS}
    catalog = pd.read_csv(processed / 'catalogo_zonas_v2.csv')
    panel = pd.read_csv(processed / 'panel_demanda_v2.csv')
    temporal = pd.read_csv(processed / 'features_temporales_v2.csv')
    if set(map(tuple, panel[KEY].to_numpy())) != set(map(tuple, temporal[KEY].to_numpy())) or len(panel) != len(temporal):
        raise ValueError('Master and temporal panel keys differ')
    geojson = json.loads((processed / 'zonas_geometria.geojson').read_text())
    crosswalk = pd.read_csv(processed / 'crosswalk_colonias.csv')
    audit, neighbors, overlaps, projected, geo_info = audit_geometry(catalog, geojson)
    validate_neighbors(neighbors, catalog.zone_id)
    # Audit artifacts are computed before building lag features.
    missing = missing_geometry_report(catalog, audit, panel, crosswalk)
    stations, blank = load_stations(ROOT / 'data/raw/ecobici/Caracteristicas_estaciones.csv')
    rebuilt, stations = build_catalog(stations, crosswalk, geojson,
        json.loads((ROOT / 'config/aliases_colonias_v2.json').read_text())['approved_aliases'])
    if set(rebuilt.zone_id) != set(catalog.zone_id):
        raise ValueError('Station assignments and V2 catalog differ')
    station_audit = station_geometry_audit(stations, projected)
    spatial = build_spatial_features(panel, catalog, audit, neighbors)
    combined = combine_features(temporal, spatial)
    frames = dict(zip(OUTPUTS[:7], [audit, neighbors, overlaps, missing, station_audit, spatial, combined]))
    for name, frame in frames.items():
        frame.to_csv(processed / name, index=False)
    metadata = {'pipeline_version': VERSION, 'created_at': datetime.now(timezone.utc).isoformat(),
                'git_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                'run_id': hashlib.sha256(json.dumps(fingerprints, sort_keys=True).encode()).hexdigest()[:16],
                'source_geojson': 'data/processed/zonas_geometria.geojson',
                'source_geojson_hash': fingerprints['data/processed/zonas_geometria.geojson'],
                'input_and_implementation_sha256': fingerprints, **geo_info,
                'neighbor_method': 'queen_exact_source_topology', 'weight_method': 'binary_row_normalized; renormalize over valid observations',
                'fallback_method': 'disabled', 'n_zones': len(catalog),
                'n_zones_with_geometry': int(audit.geometry_available.sum()),
                'n_zones_without_geometry': int((~audit.geometry_available).sum()),
                'n_edges': len(neighbors), 'n_edges_undirected': len(neighbors) // 2,
                'n_isolated_zones': int((audit.geometry_usable & audit.n_neighbors_queen.eq(0)).sum()),
                'n_distance_fallback_zones': 0, 'n_stations_with_coordinates': len(stations),
                'n_station_spatial_conflicts': int(station_audit.status.eq('outside').sum()),
                'n_stations_without_catalog_polygon': int(station_audit.status.eq('missing_catalog_polygon').sum()),
                'n_stations_multiple_covering_polygons': int(station_audit.n_covering_polygons.gt(1).sum()),
                'n_blank_station_rows': blank, 'n_panel_rows': len(combined),
                'mean_neighbor_coverage_connected_zone_months': float(spatial.neighbor_observation_coverage.mean()),
                'n_zone_months_with_spatial_features': int(spatial.spatial_features_available.sum()),
                'coverage_denominator_zone_months': int(spatial.neighbor_observation_coverage.notna().sum()),
                'default_causal_features': CAUSAL, 'features': feature_registry(),
                'runtime': {'pandas': pd.__version__, 'numpy': np.__version__, 'shapely': shapely.__version__, 'pyproj': pyproj.__version__},
                'limitations': ['Fixed current geometry and station assignments lack historical validity.',
                    'Source topology has overlaps and missing polygons; exact Queen may omit near contacts.',
                    'Earliest-availability guards are lower bounds, not certified historical publication times.',
                    'Forecast at horizon h must freeze features at its origin; target-month features cannot be used directly for h>1.',
                    'No evidence of predictive improvement is claimed without subsequent comparison on common splits.'],
                'output_sha256': {name: sha256_file(processed / name) for name in frames}}
    for rel, digest in protected.items():
        if sha256_file(ROOT / rel) != digest:
            raise AssertionError(f'Protected previous-phase file changed: {rel}')
    metadata['protected_previous_phase_sha256'] = protected
    for name in OUTPUTS[7:]:
        (processed / name).write_text(json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print(json.dumps({k: v for k, v in metadata.items() if k.startswith('n_') or k.startswith('mean_') or k == 'run_id'}, indent=2))


if __name__ == '__main__':
    main()
