"""Phase 4: frozen-origin, same-row temporal/spatial point LightGBM comparison.

python -B -m src.models.lightgbm_compare_v2
No tuning, early stopping, application changes, new cuts or legacy overwrites.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import scipy
import sklearn

from src.data.ecobici_v2 import sha256_file
from src.features.model_matrices_v2 import (
    KEY, TEMPORAL_CANDIDATES, SPATIAL_FEATURES, candidate_matrix, choose_temporal_features,
    feature_availability, model_matrices, review_overlaps, select_X,
)
from src.validation.rolling_validation_v2 import calculate_metrics, DIRECTIONAL_ACCURACY_THRESHOLD

ROOT = Path(__file__).resolve().parents[2]
VERSION = '2.0-phase4-comparison'
MODELS = ['PERSISTENCE', 'LGBM_TEMPORAL', 'LGBM_TEMPORAL_SPATIAL']
SCOPES = ['EVALUATION_ALL', 'EVALUATION_SPATIAL_COMPARABLE']
PARAMS = dict(objective='regression', n_estimators=300, learning_rate=0.03,
              num_leaves=15, min_child_samples=20, colsample_bytree=0.8,
              random_state=42, subsample=1.0, subsample_freq=0,
              n_jobs=1, deterministic=True, force_col_wise=True,
              use_missing=True, zero_as_missing=False, verbosity=-1)
MIN_TRAIN_ROWS = 40
TIE_RTOL = 1e-8
# Descriptive pre-fixed flags, not significance tests or tuning criteria.
GAP_RATIO = 3.0
SEVERE_LOSS_PCT = -25.0
SEVERE_CUT_FRACTION = 0.25
CSV_OUTPUTS = ['model_matrix_temporal_v2.csv', 'model_matrix_temporal_spatial_v2.csv',
 'lightgbm_compare_predictions_v2.csv', 'lightgbm_compare_cut_metrics_v2.csv',
 'lightgbm_compare_metrics_v2.csv', 'lightgbm_compare_zone_metrics_v2.csv',
 'lightgbm_compare_feature_importance_v2.csv', 'feature_availability_v2.csv',
 'geospatial_overlaps_review_v2.csv', 'feature_coverage_v2.csv',
 'lightgbm_compare_run_audit_v2.csv', 'lightgbm_compare_overfitting_v2.csv',
 'lightgbm_compare_spatial_value_v2.csv', 'lightgbm_compare_coverage_metrics_v2.csv']
META_NAME = 'lightgbm_compare_v2.metadata.json'


def improvement_pct(reference, candidate):
    if not np.isfinite([reference, candidate]).all() or reference <= 0:
        return np.nan
    return float((reference - candidate) / reference * 100)


def eligible_masks(frame, temporal):
    # Lag1 is the available persistence anchor shared by all three estimators.
    all_mask = frame.target_viajes_total.notna() & frame.lag_1.notna()
    comparable = all_mask & frame[temporal + SPATIAL_FEATURES].notna().all(axis=1)
    return {SCOPES[0]: all_mask, SCOPES[1]: comparable}


def training_rows(matrix, origin, horizon):
    issue = (pd.Period(origin, freq='M') + 1).to_timestamp()
    return matrix[(matrix.horizon == horizon) & (matrix.origin_period < origin)
                  & (matrix.target_period <= origin)
                  & matrix.target_viajes_total.notna() & matrix.lag_1.notna()
                  & pd.to_datetime(matrix.label_available_no_earlier_than, format='ISO8601').le(issue)].copy()


def row_hash(frame):
    content = frame[KEY].sort_values(KEY).to_csv(index=False).encode()
    return hashlib.sha256(content).hexdigest()


def metrics_for(group):
    result = calculate_metrics(group.actual, group.predicted, group.origin_value)
    result['n_observations'] = result.pop('n_predictions')
    return result


def run_models(matrix, splits, feature_sets, registry, verbose=True):
    used = splits[splits.status.eq('USED')].sort_values(['horizon', 'origin_period'])
    if used.split_id.duplicated().any() or used.duplicated(['horizon', 'origin_period']).any():
        raise ValueError('Duplicate rolling split')
    predictions, cuts, audit, fit_metrics, importance = [], [], [], [], []
    temporal = feature_sets['LGBM_TEMPORAL']
    for split in used.itertuples():
        h, origin, destination = split.horizon, split.origin_period, split.target_period
        if str(pd.Period(origin, freq='M') + h) != destination:
            raise ValueError('Inconsistent split destination')
        train = training_rows(matrix, origin, h).sort_values(KEY)
        test = matrix[(matrix.horizon == h) & matrix.origin_period.eq(origin)].sort_values(KEY).copy()
        if not test.target_period.eq(destination).all() or test.empty:
            raise ValueError('Matrix does not match existing split')
        masks = eligible_masks(test, temporal)
        estimable = len(train) >= MIN_TRAIN_ROWS
        full_preds = {'PERSISTENCE': test.lag_1.to_numpy(dtype=float)}
        n_missing = int(test[SPATIAL_FEATURES].isna().any(axis=1).sum())
        for model, features in feature_sets.items():
            if estimable:
                Xtrain, Xtest = select_X(train, features, registry), select_X(test, features, registry)
                estimator = lgb.LGBMRegressor(**PARAMS)
                estimator.fit(Xtrain, train.target_viajes_total)
                ypred = estimator.predict(Xtest)
                fitted = estimator.predict(Xtrain)
                if not np.isfinite(ypred).all() or not np.isfinite(fitted).all():
                    raise AssertionError('Nonfinite LightGBM prediction')
                full_preds[model] = ypred
                train_mae = float(np.mean(np.abs(fitted - train.target_viajes_total.to_numpy())))
                for f, gain, count in zip(features, estimator.booster_.feature_importance('gain'),
                                          estimator.booster_.feature_importance('split')):
                    importance.append({'feature_name': f, 'gain_importance': float(gain), 'split_importance': int(count),
                                       'model_type': model, 'horizon': h, 'origin_period': origin})
            else:
                train_mae = np.nan
                full_preds[model] = np.full(len(test), np.nan)
            for scope, mask in masks.items():
                selected = test.loc[mask]
                mae = float(np.mean(np.abs(full_preds[model][mask.to_numpy()] - selected.target_viajes_total))) if len(selected) and estimable else np.nan
                ratio = mae / train_mae if train_mae > 0 else np.nan
                fit_metrics.append({'evaluation_scope': scope, 'model': model, 'horizon': h,
                                    'origin_period': origin, 'target_period': destination,
                                    'train_MAE': train_mae, 'validation_MAE': mae,
                                    'validation_train_mae_ratio': ratio, 'large_gap_flag': bool(np.isfinite(ratio) and ratio > GAP_RATIO),
                                    'n_train': len(train), 'n_validation': len(selected),
                                    'max_train_label_period': train.target_period.max() if len(train) else None})
        for scope, mask in masks.items():
            selected = test.loc[mask]
            for model in MODELS:
                n_usable = len(selected) if estimable else 0
                audit.append({'evaluation_scope': scope, 'model': model, 'horizon': h,
                              'split_id': split.split_id, 'origin_period': origin, 'target_period': destination,
                              'n_rows_total': len(test), 'n_rows_usable': n_usable,
                              'n_rows_with_spatial_missing': n_missing, 'n_rows_excluded': len(test) - n_usable,
                              'n_spatial_missing_in_scope': int(selected[SPATIAL_FEATURES].isna().any(axis=1).sum()),
                              'n_train': len(train), 'train_row_hash': row_hash(train), 'test_row_hash': row_hash(selected),
                              'status': 'USED' if n_usable else 'NO_USABLE_ROWS' if estimable else 'INSUFFICIENT_TRAINING',
                              'hyperparameters_json': json.dumps(PARAMS, sort_keys=True) if model != 'PERSISTENCE' else None})
                output = pd.DataFrame(columns=['actual', 'predicted', 'origin_value'])
                if n_usable:
                    output = selected[['zone_id', 'origin_period', 'horizon', 'target_period', 'neighbor_observation_coverage']].copy()
                    output['evaluation_scope'], output['model'], output['split_id'] = scope, model, split.split_id
                    output['actual'] = selected.target_viajes_total.to_numpy()
                    output['predicted'] = full_preds[model][mask.to_numpy()]
                    output['origin_value'] = selected.lag_1.to_numpy()
                    if not np.isfinite(output[['actual', 'predicted', 'origin_value']]).all().all():
                        raise AssertionError('Nonfinite scored value')
                    predictions.append(output)
                cuts.append({'evaluation_scope': scope, 'model': model, 'horizon': h, 'split_id': split.split_id,
                             'origin_period': origin, 'target_period': destination, **metrics_for(output)})
        if verbose:
            print(f'h={h} origin={origin}: train={len(train)} all={int(masks[SCOPES[0]].sum())} comparable={int(masks[SCOPES[1]].sum())}', flush=True)
    if not predictions:
        raise ValueError('No evaluable predictions; inspect training and availability')
    return (pd.concat(predictions, ignore_index=True), pd.DataFrame(cuts), pd.DataFrame(audit),
            pd.DataFrame(fit_metrics), pd.DataFrame(importance))


def aggregate_metrics(predictions, cut_metrics):
    rows = []
    for (scope, model, h), planned in cut_metrics.groupby(['evaluation_scope', 'model', 'horizon']):
        p = predictions[(predictions.evaluation_scope == scope) & (predictions.model == model) & (predictions.horizon == h)]
        rows.append({'evaluation_scope': scope, 'model': model, 'horizon': h,
                     'n_cuts': int(p.origin_period.nunique()), 'n_cuts_planned': len(planned), **metrics_for(p)})
    metrics = pd.DataFrame(rows)
    for index, row in metrics.iterrows():
        baseline = metrics[(metrics.evaluation_scope == row.evaluation_scope) & (metrics.horizon == row.horizon) & metrics.model.eq('PERSISTENCE')].iloc[0]
        model_cuts = cut_metrics[(cut_metrics.evaluation_scope == row.evaluation_scope) & (cut_metrics.horizon == row.horizon) & cut_metrics.model.eq(row.model)]
        baseline_cuts = cut_metrics[(cut_metrics.evaluation_scope == row.evaluation_scope) & (cut_metrics.horizon == row.horizon) & cut_metrics.model.eq('PERSISTENCE')]
        paired = model_cuts.merge(baseline_cuts, on='split_id', suffixes=('_m', '_p'), validate='one_to_one')
        valid = paired.n_observations_m.gt(0)
        a, b = paired.loc[valid, 'MAE_p'], paired.loc[valid, 'MAE_m']
        tie = np.isclose(a, b, rtol=TIE_RTOL, atol=TIE_RTOL)
        metrics.loc[index, 'persistence_improvement_pct'] = improvement_pct(baseline.MAE, row.MAE)
        metrics.loc[index, 'n_cuts_model_beats_persistence'] = int(((b < a) & ~tie).sum())
        metrics.loc[index, 'n_cuts_model_loses_to_persistence'] = int(((b > a) & ~tie).sum())
        metrics.loc[index, 'n_cuts_model_ties_persistence'] = int(tie.sum())
    return metrics


def spatial_value(metrics, cuts, fit):
    rows = []
    for (scope, h), group in metrics.groupby(['evaluation_scope', 'horizon']):
        by_model = group.set_index('model')
        temporal, spatial = by_model.loc['LGBM_TEMPORAL'], by_model.loc['LGBM_TEMPORAL_SPATIAL']
        a = cuts[(cuts.evaluation_scope == scope) & (cuts.horizon == h) & cuts.model.eq('LGBM_TEMPORAL')]
        b = cuts[(cuts.evaluation_scope == scope) & (cuts.horizon == h) & cuts.model.eq('LGBM_TEMPORAL_SPATIAL')]
        pairs = a.merge(b, on='split_id', suffixes=('_t', '_s'), validate='one_to_one')
        pairs = pairs[pairs.n_observations_t > 0]
        gains = np.array([improvement_pct(x, y) for x, y in zip(pairs.MAE_t, pairs.MAE_s)])
        ties = np.isclose(pairs.MAE_t, pairs.MAE_s, rtol=TIE_RTOL, atol=TIE_RTOL)
        wins = int(((pairs.MAE_s < pairs.MAE_t) & ~ties).sum())
        losses = int(((pairs.MAE_s > pairs.MAE_t) & ~ties).sum())
        n = len(pairs)
        mae_gain, rmse_gain = improvement_pct(temporal.MAE, spatial.MAE), improvement_pct(temporal.RMSE, spatial.RMSE)
        fit_subset = fit[(fit.evaluation_scope == scope) & (fit.horizon == h) & fit.model.eq('LGBM_TEMPORAL_SPATIAL') & fit.n_validation.gt(0)]
        gap_fraction = float(fit_subset.large_gap_flag.mean()) if len(fit_subset) else np.nan
        severe_loss_fraction = float(np.mean(gains < SEVERE_LOSS_PCT)) if n else np.nan
        cv = float(pairs.MAE_s.std(ddof=0) / pairs.MAE_s.mean()) if n and pairs.MAE_s.mean() > 0 else np.nan
        severe = bool(n and (severe_loss_fraction >= SEVERE_CUT_FRACTION or gap_fraction >= SEVERE_CUT_FRACTION or cv > 1))
        sufficient = n >= 6 and spatial.n_observations >= 100
        label = 'NO_SPATIAL_VALUE'
        if sufficient and mae_gain > 0 and rmse_gain > 0 and wins > n / 2 and not severe:
            label = 'SPATIAL_VALUE_CONFIRMED'
        elif n and (mae_gain > 0 or rmse_gain > 0 or wins > n / 2):
            label = 'SPATIAL_VALUE_MIXED'
        feature_recommendation = 'KEEP_TEMPORAL_SPATIAL' if label == 'SPATIAL_VALUE_CONFIRMED' else 'KEEP_TEMPORAL_ONLY'
        chosen = spatial if feature_recommendation == 'KEEP_TEMPORAL_SPATIAL' else temporal
        if not sufficient:
            recommendation = 'DO_NOT_USE_YET'
        elif chosen.persistence_improvement_pct > 0 and chosen.n_cuts_model_beats_persistence > n / 2 and not severe:
            recommendation = feature_recommendation
        elif chosen.persistence_improvement_pct > 0:
            recommendation = 'KEEP_AS_SECONDARY_MODEL'
        else:
            recommendation = 'DO_NOT_USE_YET'
        rows.append({'evaluation_scope': scope, 'horizon': h, 'n_cuts_total': n,
                     'n_cuts_planned': int(temporal.n_cuts_planned), 'n_cuts_spatial_wins': wins,
                     'n_cuts_spatial_ties': int(ties.sum()), 'n_cuts_spatial_losses': losses,
                     'spatial_mae_improvement_pct': mae_gain, 'spatial_rmse_improvement_pct': rmse_gain,
                     'mean_spatial_improvement_pct': float(np.mean(gains)) if n else np.nan,
                     'median_spatial_improvement_pct': float(np.median(gains)) if n else np.nan,
                     'severe_loss_cut_fraction': severe_loss_fraction, 'large_gap_cut_fraction': gap_fraction,
                     'spatial_cut_mae_cv': cv, 'severe_instability': severe,
                     'evidence_sufficient': sufficient, 'spatial_value_label': label if n else None,
                     'feature_set_recommendation': feature_recommendation if sufficient else 'DO_NOT_USE_YET',
                     'lightgbm_recommendation': recommendation})
    return pd.DataFrame(rows)


def coverage_analysis(predictions):
    p = predictions[predictions.evaluation_scope.eq(SCOPES[1])].copy()
    unique = p[p.model.eq('PERSISTENCE')]
    q1, q2 = unique.neighbor_observation_coverage.quantile([1/3, 2/3]).tolist()
    def bucket(v):
        # Never split identical coverage values artificially when quantiles tie.
        return 'LOW_COVERAGE' if v < q1 else 'MEDIUM_COVERAGE' if v < q2 else 'HIGH_COVERAGE'
    p['coverage_bucket'] = p.neighbor_observation_coverage.map(bucket)
    rows = []
    for (h, b, model), g in p.groupby(['horizon', 'coverage_bucket', 'model']):
        rows.append({'horizon': h, 'coverage_bucket': b, 'model': model,
                     'n_observations': len(g), 'MAE': float(np.abs(g.actual - g.predicted).mean()),
                     'mean_neighbor_coverage': float(g.neighbor_observation_coverage.mean())})
    result = pd.DataFrame(rows)
    for (h, b), g in result.groupby(['horizon', 'coverage_bucket']):
        means = g.set_index('model').MAE
        result.loc[g.index, 'spatial_improvement_pct'] = improvement_pct(means['LGBM_TEMPORAL'], means['LGBM_TEMPORAL_SPATIAL'])
    return result, {'q_1_3': q1, 'q_2_3': q2, 'source': 'unique comparable prediction events, no outcome values',
                    'rule': 'LOW < q1; MEDIUM q1 <= x < q2; HIGH >= q2; tied values stay together',
                    'counts': unique.neighbor_observation_coverage.map(bucket).value_counts().to_dict()}


def zone_analysis(predictions, catalog):
    wide = predictions.pivot(index=['evaluation_scope', 'zone_id', 'horizon', 'origin_period', 'target_period', 'actual', 'origin_value'],
                             columns='model', values='predicted').reset_index()
    coverage = predictions[predictions.model.eq('PERSISTENCE')][['evaluation_scope', 'zone_id', 'horizon', 'origin_period', 'neighbor_observation_coverage']]
    wide = wide.merge(coverage, on=['evaluation_scope', 'zone_id', 'horizon', 'origin_period'], validate='one_to_one')
    rows = []
    for (scope, zone), g in wide.groupby(['evaluation_scope', 'zone_id']):
        errors = {m: float(np.abs(g.actual - g[m]).mean()) for m in MODELS}
        rows.append({'evaluation_scope': scope, 'zone_id': zone, 'n_predictions': len(g),
                     'mae_persistence': errors['PERSISTENCE'], 'mae_temporal': errors['LGBM_TEMPORAL'],
                     'mae_temporal_spatial': errors['LGBM_TEMPORAL_SPATIAL'],
                     'spatial_improvement_pct': improvement_pct(errors['LGBM_TEMPORAL'], errors['LGBM_TEMPORAL_SPATIAL']),
                     'mean_neighbor_coverage': g.neighbor_observation_coverage.mean()})
    return pd.DataFrame(rows).merge(catalog[['zone_id', 'colonia']], on='zone_id', validate='many_to_one')


def feature_coverage(matrix, used, selection):
    frames = []
    tests = matrix.merge(used[['horizon', 'origin_period']], on=['horizon', 'origin_period'], validate='many_to_one')
    for h, g in tests.groupby('horizon'):
        all_g = g[eligible_masks(g, selection['selected'])[SCOPES[0]]]
        for name in TEMPORAL_CANDIDATES + SPATIAL_FEATURES:
            frames.append({'feature_name': name, 'horizon': h, 'n_rows_total': len(g),
                           'n_valid': int(g[name].notna().sum()), 'coverage': float(g[name].notna().mean()),
                           'coverage_evaluation_all': float(all_g[name].notna().mean()),
                           'calibration_coverage': selection['calibration_coverage'].get(name, np.nan),
                           'selected_for_model': name in selection['selected'] + SPATIAL_FEATURES})
    return pd.DataFrame(frames)


def main():
    p = ROOT / 'data/processed'
    outputs = set(CSV_OUTPUTS + [META_NAME])
    protected = {str(f.relative_to(ROOT)): sha256_file(f) for f in p.rglob('*') if f.is_file() and f.name not in outputs}
    protected.update({str(f.relative_to(ROOT)): sha256_file(f) for f in (ROOT / 'src/app').glob('*.py')})
    source_names = ['panel_demanda_v2.csv', 'features_temporales_v2.csv', 'features_espaciales_v2.csv',
                    'features_temporal_spatial_v2.csv', 'rolling_splits_v2.csv', 'baseline_metrics_v2.csv',
                    'zone_neighbors_v2.csv', 'geospatial_audit_v2.csv', 'geospatial_overlaps_v2.csv', 'catalogo_zonas_v2.csv']
    input_paths = [p / n for n in source_names] + [Path(__file__), ROOT / 'src/features/model_matrices_v2.py',
                     ROOT / 'src/validation/rolling_validation_v2.py', ROOT / 'requirements-model-compare-v2.txt',
                     ROOT / 'src/features/features_temporales_v2.py', ROOT / 'src/features/features_espaciales_v2.py']
    fingerprints = {str(f.relative_to(ROOT)): sha256_file(f) for f in input_paths}
    panel, neighbors, splits, catalog = (pd.read_csv(p / name) for name in
        ['panel_demanda_v2.csv', 'zone_neighbors_v2.csv', 'rolling_splits_v2.csv', 'catalogo_zonas_v2.csv'])
    matrix = candidate_matrix(panel, neighbors)
    selected, selection = choose_temporal_features(matrix, splits)
    matrices, sets = model_matrices(matrix, selected)
    previous_columns = pd.read_csv(p / 'features_temporal_spatial_v2.csv', nrows=0).columns.tolist()
    registry = feature_availability(previous_columns + panel.columns.tolist() + matrix.columns.tolist(), selected)
    overlaps = review_overlaps(pd.read_csv(p / 'geospatial_overlaps_v2.csv'), pd.read_csv(p / 'geospatial_audit_v2.csv'))
    print('Frozen feature selection:', json.dumps(selection), flush=True)
    # 4A/4B/4C artifacts first; no model has been fitted yet.
    matrices['LGBM_TEMPORAL'].to_csv(p / CSV_OUTPUTS[0], index=False)
    matrices['LGBM_TEMPORAL_SPATIAL'].to_csv(p / CSV_OUTPUTS[1], index=False)
    registry.to_csv(p / 'feature_availability_v2.csv', index=False)
    overlaps.to_csv(p / 'geospatial_overlaps_review_v2.csv', index=False)
    coverage = feature_coverage(matrix, splits[splits.status.eq('USED')], selection)
    coverage.to_csv(p / 'feature_coverage_v2.csv', index=False)
    pred, cuts, audit, fit, importance_cuts = run_models(matrix, splits, sets, registry)
    metrics = aggregate_metrics(pred, cuts)
    value = spatial_value(metrics, cuts, fit)
    buckets, bucket_info = coverage_analysis(pred)
    zones = zone_analysis(pred, catalog)
    importance = importance_cuts.groupby(['feature_name', 'model_type', 'horizon'], as_index=False).agg(
        gain_importance=('gain_importance', 'mean'), split_importance=('split_importance', 'mean'), n_fits=('origin_period', 'nunique'))
    frames = {'lightgbm_compare_predictions_v2.csv': pred, 'lightgbm_compare_cut_metrics_v2.csv': cuts,
              'lightgbm_compare_metrics_v2.csv': metrics, 'lightgbm_compare_zone_metrics_v2.csv': zones,
              'lightgbm_compare_feature_importance_v2.csv': importance, 'lightgbm_compare_run_audit_v2.csv': audit,
              'lightgbm_compare_overfitting_v2.csv': fit, 'lightgbm_compare_spatial_value_v2.csv': value,
              'lightgbm_compare_coverage_metrics_v2.csv': buckets}
    for name, frame in frames.items():
        frame.to_csv(p / name, index=False)
    for name, digest in protected.items():
        if sha256_file(ROOT / name) != digest:
            raise AssertionError('Protected file changed: ' + name)
    meta = {'pipeline_version': VERSION, 'created_at': datetime.now(timezone.utc).isoformat(),
            'git_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            'run_id': hashlib.sha256(json.dumps(fingerprints, sort_keys=True).encode()).hexdigest()[:16],
            'input_and_implementation_sha256': fingerprints, 'protected_previous_phase_sha256': protected,
            'output_sha256': {name: sha256_file(p / name) for name in CSV_OUTPUTS},
            'hyperparameters_by_model': {model: PARAMS for model in sets},
            'feature_sets': sets, 'feature_selection': selection, 'target': 'viajes_total at origin+h',
            'training': 'same expanding rows for both estimators; label_month<=origin and label earliest availability<=issue',
            'issuance': 'start of origin+1; demand months<=origin; earliest-availability guard on all inputs',
            'evaluation_all': 'available target and lag1 persistence anchor; other selected predictors may be NaN',
            'evaluation_spatial_comparable': 'ALL plus every selected temporal and spatial predictor nonmissing; same predictions, no retraining',
            'missing_policy': 'native NaN in LightGBM; zero_as_missing=false; no fillna(0)',
            'temporal_calendar': 'calendar features refer to known destination month; demand features use t=origin+1 semantics',
            'overlap_rule': 'boundary if area<=1m2 and max percent<=0.001; small if area<=1000m2 and max percent<1; otherwise material; invalid measurement requires review',
            'overlap_counts': overlaps.category.value_counts().to_dict(), 'queen_changed': False, 'geometries_excluded': [],
            'coverage_buckets': bucket_info, 'directional_accuracy_threshold': DIRECTIONAL_ACCURACY_THRESHOLD,
            'metrics_implementation': 'src/validation/rolling_validation_v2.py::calculate_metrics, unchanged',
            'importance_aggregation': 'mean gain and split count over fits per horizon; not causal explanation',
            'stability_rules': {'min_cuts': 6, 'min_observations': 100, 'large_validation_train_mae_ratio': GAP_RATIO,
                'severe_spatial_cut_loss_pct': SEVERE_LOSS_PCT, 'severe_fraction': SEVERE_CUT_FRACTION, 'cut_mae_cv_limit': 1},
            'runtime': {'numpy': np.__version__, 'pandas': pd.__version__, 'lightgbm': lgb.__version__,
                        'scipy': scipy.__version__, 'scikit_learn': sklearn.__version__},
            'used_splits': splits[splits.status.eq('USED')].groupby('horizon').size().to_dict(),
            'limitations': ['Historical publication times and source revisions remain unverified; availability dates are lower bounds.',
                'Fixed Queen geometry and station-to-colony assignment inherit partial coverage and audit conflicts.',
                'Comparable complete-case subset is selected by availability, not representative of all 106 zones.',
                'Pooled R2 and absolute errors are strongly affected by heterogeneous colony scales.',
                'Overlapping horizons/cuts and shared zones are dependent; no significance or causal claim.',
                'One fixed configuration and seed; importance and coverage buckets are descriptive only.',
                'Missing origin observations are excluded from ALL to compare honestly with unchanged persistence semantics.']}
    (p / META_NAME).write_text(json.dumps(meta, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print(metrics.to_string(index=False), flush=True)
    print(value.to_string(index=False), flush=True)


if __name__ == '__main__':
    main()
