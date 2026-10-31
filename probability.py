"""Chronological out-of-sample 1h direction calibration from archived completed runs.

Not a claim of true or guaranteed probabilities. No look-ahead: each observation
uses a completed snapshot's score and the next snapshot's price only.
"""
import datetime as dt
import math
from collections import defaultdict

MIN_TRAIN = 200
MIN_TEST = 80
MIN_BUCKET_TRAIN = 25
BUCKETS = ((0, 39), (40, 54), (55, 69), (70, 84), (85, 100))


def bucket(score):
    for low, high in BUCKETS:
        if low <= score <= high:
            return f'{low}-{high}'
    return None


def parse_time(value):
    try:
        return dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (TypeError, ValueError, AttributeError):
        return None


def observations(snapshots):
    snaps = sorted((s for s in snapshots if isinstance(s, dict) and parse_time(s.get('at'))), key=lambda s: s['at'])
    out = []
    for a, b in zip(snaps, snaps[1:]):
        ta, tb = parse_time(a['at']), parse_time(b['at'])
        gap = (tb - ta).total_seconds() / 60
        if not 45 <= gap <= 90:
            continue
        sa, sb = a.get('scores', {}), b.get('scores', {})
        if not isinstance(sa, dict) or not isinstance(sb, dict):
            continue
        for market, pair in sa.items():
            later = sb.get(market)
            if not (isinstance(pair, list) and len(pair) >= 2 and isinstance(later, list) and len(later) >= 2):
                continue
            score, price, next_price = pair[0], pair[1], later[1]
            if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (score, price, next_price)) or price <= 0 or next_price <= 0:
                continue
            key = bucket(score)
            if key is not None:
                out.append({'at': a['at'], 'market': market, 'bucket': key, 'up': int(next_price > price)})
    return out


def calculate(snapshots, markets):
    obs = observations(snapshots)
    times = sorted({x['at'] for x in obs})
    status = {'status': 'insufficient', 'definition': '다음 분석 시점(45~90분 후) 가격이 이전 분석 시점보다 상승한 비율',
              'method': '과거 1시간 간격 분석 기록의 점수 구간별 상승 빈도; 시간 순서 70% 학습/30% 검증; Laplace 평활',
              'train_samples': 0, 'test_samples': 0, 'brier_score': None, 'baseline_brier': None,
              'direction_accuracy': None, 'validation_up_rate': None, 'snapshot_intervals': len(times),
              'min_train': MIN_TRAIN, 'min_test': MIN_TEST, 'min_bucket_train': MIN_BUCKET_TRAIN,
              'note': '검증 부족인 경우 확률 미표시. 표본은 여러 코인·시간대가 중복 포함되어 독립적이지 않을 수 있음.'}
    if len(times) < 24:
        return status, {}
    split = max(1, int(len(times) * .7))
    if split >= len(times):
        return status, {}
    cutoff = times[split]
    train = [x for x in obs if x['at'] < cutoff]
    test = [x for x in obs if x['at'] >= cutoff]
    status['train_samples'] = len(train)
    status['test_samples'] = len(test)
    if len(train) < MIN_TRAIN or len(test) < MIN_TEST:
        return status, {}
    grouped = defaultdict(list)
    for row in train:
        grouped[row['bucket']].append(row['up'])
    overall = (sum(x['up'] for x in train) + 1) / (len(train) + 2)
    probs = {}
    for key, outcomes in grouped.items():
        if len(outcomes) >= MIN_BUCKET_TRAIN:
            # Conservative shrinkage to overall base rate.
            probs[key] = (sum(outcomes) + 30 * overall) / (len(outcomes) + 30)
    evaluated = [x for x in test if x['bucket'] in probs]
    if len(evaluated) < MIN_TEST:
        return status, {}
    status['status'] = 'validated'
    status['test_samples'] = len(evaluated)
    status['brier_score'] = round(sum((probs[x['bucket']] - x['up'])**2 for x in evaluated) / len(evaluated), 4)
    status['baseline_brier'] = round(sum((overall - x['up'])**2 for x in evaluated) / len(evaluated), 4)
    status['direction_accuracy'] = round(100 * sum(int((probs[x['bucket']] >= .5) == bool(x['up'])) for x in evaluated) / len(evaluated), 1)
    status['validation_up_rate'] = round(100 * sum(x['up'] for x in evaluated) / len(evaluated), 1)
    status['buckets'] = {key: {'train_samples': len(grouped[key]), 'up_rate_pct': round(100 * probs[key], 1)} for key in probs}
    market_prob = {}
    for r in markets:
        key = bucket(r['score'])
        if key in probs:
            market_prob[r['market']] = {'probability_1h_pct': round(100 * probs[key], 1),
                                        'training_bucket_samples': len(grouped[key]), 'score_bucket': key}
    return status, market_prob
