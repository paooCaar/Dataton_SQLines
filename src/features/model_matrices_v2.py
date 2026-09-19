"""Origin-frozen matrices for Phase 4; no changes to Phase 2/3 artifacts."""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.features.features_temporales_v2 import FEATURE_COLUMNS, LAGS, WINDOWS
from src.features.features_espaciales_v2 import DYNAMIC, STATIC, validate_neighbors

TEMPORAL_CANDIDATES = list(FEATURE_COLUMNS)
SPATIAL_FEATURES = list(DYNAMIC)
CALENDAR = ['month', 'year', 'sin_month', 'cos_month']
KEY = ['zone_id', 'origin_period', 'horizon']
HISTORY_COVERAGE_MIN = 0.60  # frozen before evaluating outcomes; calibration only


def validate_panel(panel):
    if panel[['zone_id', 'periodo']].isna().any().any() or panel.duplicated(['zone_id', 'periodo']).any():
        raise ValueError('Nonunique or null panel key')
    if 'target_available_no_earlier_than' not in panel:
        raise ValueError('Availability metadata is required')


def origin_features(panel, neighbors, origin):
    """Same phase-2 formulas at t=origin+1, masked to the same issue time.

    All demand inputs have event month <= origin and earliest availability <=
    start(origin+1). No destination feature row is ever read.
    """
    origin = pd.Period(origin, freq='M')
    issue = (origin + 1).to_timestamp()
    zones = sorted(panel.zone_id.unique())
    period = pd.PeriodIndex(panel.periodo, freq='M')
    history = panel.loc[period <= origin].copy()
    valid = history.data_status.isin(['OBSERVED', 'ZERO_DEMAND'])
    available = pd.to_datetime(history.target_available_no_earlier_than, format='ISO8601')
    history['value'] = history.viajes_total.where(valid & available.notna() & available.le(issue))
    wide = history.pivot(index='zone_id', columns='periodo', values='value').reindex(zones)
    months = [str(origin - k) for k in range(13)]
    y = wide.reindex(columns=months).to_numpy(dtype=float)
    result = pd.DataFrame({'zone_id': zones, 'origin_period': str(origin), 'feature_reference_period': str(origin + 1),
                           'issue_time': issue.isoformat()})
    for k in LAGS:
        result[f'lag_{k}'] = y[:, k - 1]
        result[f'growth_{k}'] = np.divide(y[:, 0] - y[:, k], np.abs(y[:, k]),
            out=np.full(len(zones), np.nan), where=np.isfinite(y[:, k]) & (y[:, k] != 0))
    for w in WINDOWS:
        values = y[:, :w][:, ::-1]  # calendar order, oldest to newest
        result[f'rolling_mean_{w}'] = values.mean(axis=1)
        result[f'rolling_std_{w}'] = values.std(axis=1, ddof=1)
        x = np.arange(w) - (w - 1) / 2
        result[f'trend_{w}'] = values @ x / np.dot(x, x)
    # Fixed Queen graph, demand-only features; no station/geometry descriptors.
    index = {z: i for i, z in enumerate(zones)}
    for name in SPATIAL_FEATURES:
        result[name] = np.nan
    for zone, edges in neighbors.groupby('zone_id', sort=True):
        ids = [index[z] for z in edges.neighbor_zone_id]
        weights = edges.weight_normalized.to_numpy(dtype=float)
        i = index[zone]
        for target, source in [('neighbor_trips_lag1', 'lag_1'), ('neighbor_growth_lag1', 'growth_1'),
                               ('neighbor_trips_mean_lag3', 'rolling_mean_3')]:
            values = result.loc[ids, source].to_numpy(dtype=float)
            valid = np.isfinite(values)
            if valid.any():
                result.loc[i, target] = np.dot(weights[valid], values[valid]) / weights[valid].sum()
        valid = np.isfinite(result.loc[ids, 'lag_1'].to_numpy(dtype=float))
        result.loc[i, 'neighbor_active_zones'] = int(valid.sum())
        result.loc[i, 'neighbor_observation_coverage'] = weights[valid].sum()
    return result


def candidate_matrix(panel, neighbors, horizons=(1, 3, 6, 12)):
    validate_panel(panel)
    validate_neighbors(neighbors, panel.zone_id.unique())
    periods = pd.period_range(panel.periodo.min(), panel.periodo.max(), freq='M')
    target = panel[['zone_id', 'periodo', 'viajes_total', 'target_available_no_earlier_than', 'data_status']].copy()
    target['viajes_total'] = target.viajes_total.where(target.data_status.isin(['OBSERVED', 'ZERO_DEMAND']))
    target = target.rename(columns={'periodo': 'target_period', 'viajes_total': 'target_viajes_total',
                                    'target_available_no_earlier_than': 'label_available_no_earlier_than'})
    frames = []
    for origin in periods:
        origin_frame = origin_features(panel, neighbors, origin)
        for h in horizons:
            if origin + h > periods[-1]:
                continue
            frame = origin_frame.copy()
            frame['horizon'], frame['target_period'] = h, str(origin + h)
            # Future calendar is deterministic and known at issuance.
            frame['month'], frame['year'] = (origin + h).month, (origin + h).year
            angle = 2 * np.pi * (frame.month - 1) / 12
            frame['sin_month'], frame['cos_month'] = np.sin(angle), np.cos(angle)
            frame = frame.merge(target.drop(columns='data_status'), on=['zone_id', 'target_period'], validate='one_to_one')
            frames.append(frame)
    result = pd.concat(frames, ignore_index=True).sort_values(KEY).reset_index(drop=True)
    if result.duplicated(KEY).any():
        raise AssertionError('Duplicated modeling row')
    return result


def choose_temporal_features(matrix, splits):
    """Coverage selection before the earliest test origin; never based on errors.

    Use one-step historical pairs whose labels were available by the first
    USED origin. This gives all horizons the exact same pre-frozen feature set.
    """
    first = splits.loc[splits.status.eq('USED'), 'origin_period'].min()
    issue = (pd.Period(first, freq='M') + 1).to_timestamp()
    calibration = matrix[(matrix.horizon == 1) & (matrix.target_period <= first)
                         & matrix.target_viajes_total.notna() & matrix.lag_1.notna()
                         & pd.to_datetime(matrix.label_available_no_earlier_than, format='ISO8601').le(issue)]
    if calibration.empty:
        raise ValueError('No initial calibration rows for coverage-only feature selection')
    coverage = calibration[TEMPORAL_CANDIDATES].notna().mean()
    selected = [f for f in TEMPORAL_CANDIDATES if coverage[f] >= HISTORY_COVERAGE_MIN or f in CALENDAR]
    if 'lag_1' not in selected:
        raise AssertionError('Lag1 anchor missing')
    info = {'calibration_end': first, 'calibration_rows': len(calibration), 'coverage_threshold': HISTORY_COVERAGE_MIN,
            'selected': selected, 'calibration_coverage': coverage.to_dict()}
    return selected, info


def model_matrices(candidates, temporal_features):
    identifiers = ['zone_id', 'origin_period', 'horizon', 'target_period', 'feature_reference_period',
                   'issue_time', 'target_viajes_total', 'label_available_no_earlier_than']
    sets = {'LGBM_TEMPORAL': list(temporal_features), 'LGBM_TEMPORAL_SPATIAL': list(temporal_features) + SPATIAL_FEATURES}
    return {model: candidates[identifiers + features].copy() for model, features in sets.items()}, sets


def feature_availability(all_columns, selected):
    rows = []
    for name in sorted(set(all_columns) | set(TEMPORAL_CANDIDATES) | set(SPATIAL_FEATURES) | set(STATIC)):
        temporal, spatial = name in TEMPORAL_CANDIDATES, name in SPATIAL_FEATURES
        safe = temporal or spatial
        snapshot = name in STATIC or any(k in name for k in ['snapshot', 'poblacion', 'denue', 'ciclovia', 'accidentes'])
        group = 'TEMPORAL_SAFE' if temporal else 'SPATIAL_SAFE' if spatial else 'DESCRIPTIVE_ONLY' if snapshot else 'BLOCKED_HISTORICAL'
        note = 'Conditional on earliest-availability guard; actual publication vintage unverified'
        if temporal and name not in selected: note = 'Safe formula; excluded by initial-history coverage rule'
        if not safe: note = 'Excluded: snapshot, fixed geometry descriptor, identifier, label or incidental metadata'
        rows.append({'feature_name': name, 'feature_group': group, 'historical_safe': safe,
                     'reference_time': 'known destination calendar' if name in CALENDAR else 'demand through origin; issue=start(origin+1)' if safe else 'not a rolling predictor',
                     'uses_target_history': safe and name not in CALENDAR, 'uses_static_snapshot': snapshot,
                     'allowed_in_rolling_model': name in selected or spatial, 'notes': note})
    return pd.DataFrame(rows)


def select_X(frame, features, registry):
    allowed = set(registry.loc[registry.allowed_in_rolling_model & registry.historical_safe &
        registry.feature_group.isin(['TEMPORAL_SAFE', 'SPATIAL_SAFE']), 'feature_name'])
    if not set(features) <= allowed or len(set(features)) != len(features):
        raise ValueError('Disallowed, unsafe or duplicated model feature')
    X = frame[features].astype(float)
    if np.isinf(X.to_numpy()).any():
        raise ValueError('Infinite features')
    return X  # NaN is intentionally preserved for LightGBM.


def review_overlaps(overlaps, audit):
    areas = audit.set_index('zone_id').area_m2
    out = overlaps.rename(columns={'zone_id': 'zone_id_a', 'other_zone_id': 'zone_id_b'}).copy()
    out['overlap_pct_zone_a'] = 100 * out.overlap_area_m2 / out.zone_id_a.map(areas)
    out['overlap_pct_zone_b'] = 100 * out.overlap_area_m2 / out.zone_id_b.map(areas)
    def classify(row):
        area, a, b = row.overlap_area_m2, row.overlap_pct_zone_a, row.overlap_pct_zone_b
        if not np.isfinite([area, a, b]).all() or area < 0 or max(a, b) > 100.000001:
            return 'REVIEW_REQUIRED'
        if area <= 1 and max(a, b) <= 0.001:
            return 'LIKELY_BOUNDARY_ARTIFACT'
        if area <= 1000 and max(a, b) < 1:
            return 'SMALL_OVERLAP'
        return 'MATERIAL_OVERLAP'
    out['category'] = out.apply(classify, axis=1)
    out['queen_changed'] = False
    out['geometry_excluded'] = False
    out['decision'] = 'retain existing graph; size classification is not proof of correct boundaries'
    return out
