#!/usr/bin/env python3
"""Upbit KRW 1h/4h reversal radar. Python 3.10+, standard library only."""
import concurrent.futures
import datetime as dt
import json
import math
import os
import random
import statistics
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = 'https://api.upbit.com/v1'
OUTPUT = Path('data/latest.json')
COUNT = 160
WORKERS = 3
REQUEST_GAP = 0.42  # ~2.4 requests/s across all workers, conservatively below candle limits
MIN_24H_KRW = 100_000_000
_lock = threading.Lock()
_next_request = 0.0


def fetch(path, params=None, retries=5):
    global _next_request
    url = API + path + ('?' + urllib.parse.urlencode(params) if params else '')
    for attempt in range(retries):
        with _lock:
            now = time.monotonic()
            wait = max(0, _next_request - now)
            _next_request = max(now, _next_request) + REQUEST_GAP
        if wait:
            time.sleep(wait)
        req = urllib.request.Request(url, headers={'User-Agent': 'UpbitReversalRadar/1.0', 'Accept': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or attempt == retries - 1:
                raise
            retry_after = e.headers.get('Retry-After')
            try:
                delay = max(float(retry_after), 2.0) if retry_after else 2 ** attempt + random.random()
            except ValueError:
                delay = 2 ** attempt + random.random()
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == retries - 1:
                raise
            delay = 2 ** attempt + random.random()
        time.sleep(min(delay, 35))
    raise RuntimeError('API retry exhausted')


def ema(values, period):
    if len(values) < period:
        return []
    k = 2 / (period + 1)
    out = [None] * (period - 1)
    current = sum(values[:period]) / period
    out.append(current)
    for v in values[period:]:
        current = v * k + current * (1 - k)
        out.append(current)
    return out


def rsi(values, period=14):
    if len(values) <= period:
        return None
    changes = [values[i] - values[i - 1] for i in range(1, len(values))]
    avg_gain = sum(max(x, 0) for x in changes[:period]) / period
    avg_loss = sum(max(-x, 0) for x in changes[:period]) / period
    series = []
    def calc(g, l):
        return 100.0 if l == 0 else 100 - 100 / (1 + g / l)
    series.append(calc(avg_gain, avg_loss))
    for change in changes[period:]:
        avg_gain = (avg_gain * (period - 1) + max(change, 0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-change, 0)) / period
        series.append(calc(avg_gain, avg_loss))
    return series


def indicators(candles):
    # API returns newest first. Work exclusively with CLOSED candles, sorted oldest first.
    close = [c['trade_price'] for c in candles]
    vol = [c['candle_acc_trade_volume'] for c in candles]
    turnover = [c['candle_acc_trade_price'] for c in candles]
    if len(close) < 65:
        raise ValueError('insufficient closed candles (<65)')
    r = rsi(close)
    fast = ema(close, 12)
    slow = ema(close, 26)
    macd = [a - b for a, b in zip(fast, slow) if a is not None and b is not None]
    signal = ema(macd, 9)
    hist = [a - b for a, b in zip(macd, signal) if b is not None]
    avg = statistics.mean(close[-20:])
    std = statistics.pstdev(close[-20:])
    upper, lower = avg + 2 * std, avg - 2 * std
    prev_avg = statistics.mean(close[-21:-1])
    prior_vol = statistics.mean(turnover[-21:-1])
    last = candles[-1]
    body = abs(last['trade_price'] - last['opening_price'])
    range_ = last['high_price'] - last['low_price']
    lower_wick = min(last['trade_price'], last['opening_price']) - last['low_price']
    return {
        'close': close[-1], 'rsi': round(r[-1], 2), 'rsi_prev': round(r[-2], 2),
        'macd': macd[-1], 'signal': signal[-1], 'hist': hist[-1], 'hist_prev': hist[-2],
        'bb_mid': avg, 'bb_upper': upper, 'bb_lower': lower, 'bb_mid_prev': prev_avg,
        'ema20': ema(close, 20)[-1],
        'turnover_ratio': round(turnover[-1] / prior_vol, 2) if prior_vol else None,
        'candle_bullish': last['trade_price'] > last['opening_price'],
        'lower_wick_ratio': round(lower_wick / range_, 3) if range_ else 0,
        'body_ratio': round(body / range_, 3) if range_ else 0,
        'last_candle_kst': last['candle_date_time_kst'],
        'sample_count': len(candles),
        'recent_low': min(c['low_price'] for c in candles[-20:]),
        'recent_high': max(c['high_price'] for c in candles[-20:]),
        'last_turnover_krw': turnover[-1],
    }


def closed_candles(market, unit):
    rows = fetch(f'/candles/minutes/{unit}', {'market': market, 'count': COUNT})
    now = dt.datetime.now(dt.timezone.utc)
    result = []
    for c in rows:
        start = dt.datetime.fromisoformat(c['candle_date_time_utc']).replace(tzinfo=dt.timezone.utc)
        if start + dt.timedelta(minutes=unit) <= now - dt.timedelta(seconds=20):
            result.append(c)
    return list(reversed(result))


def score(i1, i4, day_change):
    pts, checks = 0, []
    def add(label, condition, points):
        nonlocal pts
        if condition:
            pts += points
        checks.append({'name': label, 'met': bool(condition), 'points': points if condition else 0})
    add('1시간 RSI 상승(35~60)', 35 <= i1['rsi'] <= 60 and i1['rsi'] > i1['rsi_prev'], 18)
    add('4시간 RSI 회복', i4['rsi'] > i4['rsi_prev'] and 35 <= i4['rsi'] <= 65, 12)
    add('1시간 MACD 히스토그램 개선', i1['hist'] > i1['hist_prev'], 15)
    add('1시간 MACD 골든크로스/상향', i1['macd'] > i1['signal'], 10)
    add('4시간 MACD 히스토그램 개선', i4['hist'] > i4['hist_prev'], 10)
    add('1시간 거래대금 증가(1.5배)', (i1['turnover_ratio'] or 0) >= 1.5, 12)
    add('볼린저 하단 이탈 후 회복 영역', i1['bb_lower'] <= i1['close'] <= i1['bb_mid'] * 1.025, 10)
    add('20EMA 위 또는 양봉 아래꼬리', i1['close'] >= i1['ema20'] or (i1['candle_bullish'] and i1['lower_wick_ratio'] >= .35), 8)
    add('과열되지 않은 당일 변동률', -8 <= day_change <= 12, 5)
    return pts, checks


def analyze_market(item, ticker):
    market = item['market']
    c1 = closed_candles(market, 60)
    c4 = closed_candles(market, 240)
    i1, i4 = indicators(c1), indicators(c4)
    change = float(ticker.get('signed_change_rate', 0)) * 100
    pts, checks = score(i1, i4, change)
    return {
        'market': market, 'name': item.get('korean_name', market), 'score': pts,
        'price': ticker['trade_price'], 'change_24h_pct': round(change, 2),
        'turnover_24h_krw': round(ticker.get('acc_trade_price_24h', 0)),
        'signals': checks, 'hour1': i1, 'hour4': i4,
        'support_reference': i1['recent_low'], 'resistance_reference': i1['recent_high'],
        'status': '초기 전환 후보' if pts >= 70 else '관찰 후보' if pts >= 50 else '약한 신호',
    }


def main():
    started = dt.datetime.now(dt.timezone.utc)
    errors = []
    previous = None
    if OUTPUT.exists():
        try:
            previous = json.loads(OUTPUT.read_text(encoding='utf-8'))
        except (ValueError, OSError):
            pass
    try:
        markets = [m for m in fetch('/market/all', {'is_details': 'false'}) if m['market'].startswith('KRW-')]
        tickers = {}
        for j in range(0, len(markets), 100):
            batch = markets[j:j+100]
            for t in fetch('/ticker', {'markets': ','.join(m['market'] for m in batch)}):
                tickers[t['market']] = t
        eligible = [m for m in markets if m['market'] in tickers and tickers[m['market']].get('acc_trade_price_24h', 0) >= MIN_24H_KRW]
        excluded = len(markets) - len(eligible)
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
            tasks = {pool.submit(analyze_market, m, tickers[m['market']]): m['market'] for m in eligible}
            for idx, task in enumerate(concurrent.futures.as_completed(tasks), 1):
                market = tasks[task]
                try:
                    results.append(task.result())
                except Exception as e:
                    errors.append({'market': market, 'error': f'{type(e).__name__}: {str(e)[:180]}'})
                if idx % 30 == 0:
                    print(f'Analyzed {idx}/{len(eligible)}; success={len(results)}, errors={len(errors)}', flush=True)
        results.sort(key=lambda r: (-r['score'], -r['turnover_24h_krw'], r['market']))
        status = 'ok' if not errors else 'partial' if results else 'error'
        if not results:
            raise RuntimeError('No market analysis succeeded')
        payload = {
            'schema_version': 1, 'generated_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
            'status': status, 'source': 'Upbit public API',
            'market_count': len(markets), 'eligible_count': len(eligible),
            'excluded_low_liquidity': excluded, 'analyzed_count': len(results),
            'failed_count': len(errors), 'errors': errors[:30], 'top10': results[:10],
            'method': 'Closed 1h and 4h candles; RSI14, MACD12/26/9, BB20/2, volume turnover ratio. Score is a heuristic, not a probability.',
            'minimum_24h_turnover_krw': MIN_24H_KRW,
            'runtime_seconds': round((dt.datetime.now(dt.timezone.utc) - started).total_seconds()),
        }
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        temp = OUTPUT.with_suffix('.tmp')
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
        temp.replace(OUTPUT)
        print(f'Wrote {OUTPUT} status={status} analyzed={len(results)}')
    except Exception as e:
        print(f'FATAL: {e}', flush=True)
        # Preserve last successful result rather than replacing it with an empty ranking.
        if previous is None:
            raise
        raise SystemExit(1)

if __name__ == '__main__':
    main()
