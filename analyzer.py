#!/usr/bin/env python3
"""Upbit reversal radar v2. Standard library only; educational screening, not orders."""
import concurrent.futures
import datetime as dt
import json
import math
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
HISTORY = Path('data/history.json')
HISTORY_LIMIT = 168  # last 168 hourly executions (~7 days)
COUNT = 160
WORKERS = 3
REQUEST_GAP = .42
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
        req = urllib.request.Request(url, headers={'User-Agent':'UpbitReversalRadar/2.0','Accept':'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or attempt == retries-1:
                raise
            try:
                delay = max(2, float(e.headers.get('Retry-After') or 0)) or 2**attempt
            except ValueError:
                delay = 2**attempt + random.random()
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == retries-1:
                raise
            delay = 2**attempt + random.random()
        time.sleep(min(delay, 35))
    raise RuntimeError('API retry exhausted')


def ema(values, period):
    if len(values) < period: return [None]*len(values)
    k = 2/(period+1)
    out = [None]*(period-1)
    current = sum(values[:period])/period
    out.append(current)
    for v in values[period:]:
        current = v*k + current*(1-k)
        out.append(current)
    return out


def rsi(values, period=14):
    if len(values) <= period: return [None]*len(values)
    changes = [values[i]-values[i-1] for i in range(1,len(values))]
    gain = sum(max(x,0) for x in changes[:period])/period
    loss = sum(max(-x,0) for x in changes[:period])/period
    def calc(g,l):
        return 100 if l==0 and g>0 else 50 if l==0 else 100-100/(1+g/l)
    out = [None]*period+[calc(gain,loss)]
    for x in changes[period:]:
        gain=(gain*(period-1)+max(x,0))/period
        loss=(loss*(period-1)+max(-x,0))/period
        out.append(calc(gain,loss))
    return out


def indicators(candles):
    close=[float(c['trade_price']) for c in candles]
    turnover=[float(c['candle_acc_trade_price']) for c in candles]
    if len(close)<65: raise ValueError('insufficient closed candles (<65)')
    rr=rsi(close)
    fast=ema(close,12);slow=ema(close,26)
    macd=[a-b if a is not None and b is not None else None for a,b in zip(fast,slow)]
    valid=[x for x in macd if x is not None]
    sig=ema(valid,9)
    signal=[None]*(len(macd)-len(sig))+sig
    hist=[a-b if a is not None and b is not None else None for a,b in zip(macd,signal)]
    mean=statistics.mean(close[-20:]); std=statistics.pstdev(close[-20:])
    prior_turnover=statistics.mean(turnover[-21:-1])
    last=candles[-1]
    range_=float(last['high_price'])-float(last['low_price'])
    wick=min(float(last['trade_price']),float(last['opening_price']))-float(last['low_price'])
    recent_cross=next((j for j in range(3) if macd[-1-j] > signal[-1-j] and macd[-2-j] <= signal[-2-j]),None)
    # ATR14 uses true range with prior close, measured only on completed candles.
    tr=[max(float(candles[i]['high_price'])-float(candles[i]['low_price']),abs(float(candles[i]['high_price'])-close[i-1]),abs(float(candles[i]['low_price'])-close[i-1])) for i in range(max(1,len(close)-14),len(close))]
    atr=statistics.mean(tr) if tr else 0
    return {'close':close[-1], 'rsi':round(rr[-1],2),'rsi_prev':round(rr[-2],2),'rsi_3ago':round(rr[-4],2),
      'macd':macd[-1],'signal':signal[-1],'hist':hist[-1],'hist_prev':hist[-2],
      'macd_cross_bars_ago':recent_cross,'bb_mid':mean,'bb_upper':mean+2*std,'bb_lower':mean-2*std,
      'ema20':ema(close,20)[-1], 'turnover_ratio':round(turnover[-1]/prior_turnover,2) if prior_turnover else None,
      'candle_bullish':close[-1]>float(last['opening_price']),'lower_wick_ratio':round(wick/range_,3) if range_ else 0,
      'last_candle_kst':last['candle_date_time_kst'],'sample_count':len(close),
      'recent_low':min(float(c['low_price']) for c in candles[-20:]),
      'recent_high':max(float(c['high_price']) for c in candles[-20:]),
      'atr14':atr,'rise_6h_pct':round((close[-1]/close[-7]-1)*100,2),
      'rise_12h_pct':round((close[-1]/close[-13]-1)*100,2),
      'bb_position':round((close[-1]-(mean-2*std))/(4*std),3) if std else .5}


def closed_candles(market,unit):
    rows=fetch(f'/candles/minutes/{unit}',{'market':market,'count':COUNT})
    now=dt.datetime.now(dt.timezone.utc)
    result=[]
    for c in rows:
        start=dt.datetime.fromisoformat(c['candle_date_time_utc']).replace(tzinfo=dt.timezone.utc)
        if start+dt.timedelta(minutes=unit)<=now-dt.timedelta(seconds=20):result.append(c)
    return list(reversed(result))


def score(i1,i4,day_change):
    pts=0;checks=[]
    def add(name,condition,points):
        nonlocal pts
        if condition:pts+=points
        checks.append({'name':name,'met':bool(condition),'points':points if condition else 0})
    add('1시간 RSI 바닥 회복',35<=i1['rsi']<=58 and i1['rsi']>i1['rsi_prev'] and i1['rsi']>i1['rsi_3ago'],15)
    add('4시간 RSI 하락 둔화·회복',35<=i4['rsi']<=62 and i4['rsi']>i4['rsi_prev'],12)
    add('최근 3봉 내 1시간 MACD 골든크로스',i1['macd_cross_bars_ago'] is not None,18)
    add('1시간 MACD 히스토그램 개선',i1['hist']>i1['hist_prev'],10)
    add('4시간 MACD 히스토그램 개선',i4['hist']>i4['hist_prev'],10)
    add('거래대금 평균 대비 1.5배 이상',(i1['turnover_ratio'] or 0)>=1.5,12)
    add('볼린저 하단~중심부 회복',i1['bb_lower']<=i1['close']<=i1['bb_mid']*1.025 and i1['bb_position']<=.65,9)
    add('20EMA 회복 또는 반등 양봉',i1['close']>=i1['ema20'] or (i1['candle_bullish'] and i1['lower_wick_ratio']>=.3),8)
    add('24시간 변동률 과열 전',-7<=day_change<=8,6)
    penalty=0;warnings=[]
    if i1['rise_6h_pct']>=8:penalty+=12;warnings.append('최근 6시간 8% 이상 상승')
    if i1['rise_12h_pct']>=14:penalty+=12;warnings.append('최근 12시간 14% 이상 상승')
    if day_change>=12:penalty+=15;warnings.append('24시간 12% 이상 급등')
    if i1['rsi']>=70:penalty+=15;warnings.append('1시간 RSI 과열')
    if i1['close']>i1['bb_upper']*1.025:penalty+=10;warnings.append('볼린저 상단 과도 이탈')
    if i4['hist']<i4['hist_prev'] and i4['rsi']<i4['rsi_prev']:penalty+=7;warnings.append('4시간 흐름 약화')
    return max(0,min(100,pts-penalty)),checks,warnings,penalty


def price_plan(i1,price):
    # Observation levels, not executable orders or forecasts. Reward/risk is illustrative.
    atr=i1['atr14']
    if atr<=0 or price<=0:return None
    entry_low=max(0,price-.35*atr)
    entry_high=price+.15*atr
    stop=min(i1['recent_low']-.15*atr,price-1.5*atr)
    if stop<=0:stop=max(price*.01,price-1.5*atr)
    risk=price-stop
    target=min(i1['recent_high'],price+2*risk)
    if target<=price:target=price+1.5*risk
    return {'entry_low':entry_low,'entry_high':entry_high,'reference_price':price,
      'stop_reference':stop,'target1_reference':target,'risk_pct':round(risk/price*100,2),
      'reward_risk_ratio':round((target-price)/risk,2) if risk>0 else None,
      'method':'완성된 1시간봉 ATR14·최근 20봉 고저점 기반 관찰용 시나리오 (호가·수수료·슬리피지 미반영)'}


def analyze_market(item,ticker):
    market=item['market'];i1=indicators(closed_candles(market,60));i4=indicators(closed_candles(market,240))
    change=float(ticker.get('signed_change_rate',0))*100
    pts,checks,warnings,penalty=score(i1,i4,change)
    strength='높음' if pts>=80 and not warnings else '보통' if pts>=60 else '낮음'
    return {'market':market,'name':item.get('korean_name',market),'score':pts,'price':ticker['trade_price'],
      'change_24h_pct':round(change,2),'turnover_24h_krw':round(ticker.get('acc_trade_price_24h',0)),
      'signals':checks,'hour1':i1,'hour4':i4,'warnings':warnings,'overheat_penalty':penalty,
      'signal_consistency':strength,'trade_plan':price_plan(i1,float(ticker['trade_price'])),
      'support_reference':i1['recent_low'],'resistance_reference':i1['recent_high'],
      'status':'초기 전환 후보' if pts>=75 and not warnings else '관찰 후보' if pts>=55 else '약한 신호'}


def main():
    started=dt.datetime.now(dt.timezone.utc)
    markets=[m for m in fetch('/market/all',{'is_details':'false'}) if m['market'].startswith('KRW-')]
    tickers={}
    for j in range(0,len(markets),100):
        for t in fetch('/ticker',{'markets':','.join(m['market'] for m in markets[j:j+100])}):tickers[t['market']]=t
    eligible=[m for m in markets if m['market'] in tickers and tickers[m['market']].get('acc_trade_price_24h',0)>=MIN_24H_KRW]
    results=[];errors=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures={pool.submit(analyze_market,m,tickers[m['market']]):m['market'] for m in eligible}
        for idx,future in enumerate(concurrent.futures.as_completed(futures),1):
            try:results.append(future.result())
            except Exception as e:errors.append({'market':futures[future],'error':f'{type(e).__name__}: {str(e)[:180]}'})
            if idx%30==0:print(f'Analyzed {idx}/{len(eligible)} success={len(results)} errors={len(errors)}',flush=True)
    if not results:raise RuntimeError('No successful analyses; previous data retained')
    results.sort(key=lambda x:(-x['score'],len(x['warnings']),-x['turnover_24h_krw'],x['market']))
    payload={'schema_version':2,'generated_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
      'status':'partial' if errors else 'ok','source':'Upbit public API',
      'market_count':len(markets),'eligible_count':len(eligible),'excluded_low_liquidity':len(markets)-len(eligible),
      'analyzed_count':len(results),'failed_count':len(errors),'errors':errors[:30],
      'qualified_count':sum(r['score']>=75 and not r['warnings'] for r in results),
      'top10':results[:10],
      'markets':[{ 'market':r['market'],'name':r['name'],'score':r['score'],'price':r['price'],
        'change_24h_pct':r['change_24h_pct'],'status':r['status'],'signal_consistency':r['signal_consistency'],
        'warnings':r['warnings'],'hour1':{'rsi':r['hour1']['rsi'],'turnover_ratio':r['hour1']['turnover_ratio'],
        'macd_cross_bars_ago':r['hour1']['macd_cross_bars_ago']},
        'hour4':{'rsi':r['hour4']['rsi']},'trade_plan':r['trade_plan']} for r in results],
      'method':'Closed 1h/4h candles; RSI14, MACD12/26/9, BB20/2, turnover ratio, ATR14. Rule-based score, NOT probability. Price plan illustrative, NOT forecast.',
      'minimum_24h_turnover_krw':MIN_24H_KRW,
      'runtime_seconds':round((dt.datetime.now(dt.timezone.utc)-started).total_seconds())}
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    temp=OUTPUT.with_suffix('.tmp');temp.write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8');temp.replace(OUTPUT)
    # Persist bounded hourly score history for every successfully analyzed KRW market.
    # A missing market in a run remains a gap; it is never filled with a fabricated score.
    try:
        history=json.loads(HISTORY.read_text(encoding='utf-8')) if HISTORY.exists() else {'schema_version':1,'snapshots':[]}
        snapshots=history.get('snapshots',[])
        if not isinstance(snapshots,list):snapshots=[]
    except (ValueError,OSError,TypeError):
        snapshots=[]
    timestamp=payload['generated_at_utc']
    snapshots=[x for x in snapshots if isinstance(x,dict) and x.get('at')!=timestamp]
    snapshots.append({'at':timestamp,'scores':{r['market']:[r['score'],r['price']] for r in results}})
    snapshots=sorted(snapshots,key=lambda x:x.get('at',''))[-HISTORY_LIMIT:]
    HISTORY.parent.mkdir(parents=True,exist_ok=True)
    temp_history=HISTORY.with_suffix('.tmp')
    temp_history.write_text(json.dumps({'schema_version':1,'snapshots':snapshots},ensure_ascii=False,separators=(',',':'),allow_nan=False),encoding='utf-8')
    temp_history.replace(HISTORY)
    print(f'Wrote {OUTPUT} analyzed={len(results)} errors={len(errors)}')

if __name__=='__main__':main()
