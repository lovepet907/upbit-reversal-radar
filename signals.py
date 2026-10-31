"""Explainable, closed-candle technical evidence. No trading guarantees."""
import math
import statistics

def evaluate(c1, c4, i1, i4, change):
    """Return independent-ish evidence with transparent limitations and safety gates."""
    close=[float(c['trade_price']) for c in c1]
    high=[float(c['high_price']) for c in c1]
    low=[float(c['low_price']) for c in c1]
    vol=[float(c['candle_acc_trade_price']) for c in c1]
    if len(close)<65: raise ValueError('1시간 완성봉 65개 미만')
    price=close[-1]
    evidence=[]
    def add(group,label,ok,why,weight,kind='positive'):
        evidence.append({'group':group,'name':label,'met':bool(ok),'why':why,'weight':weight,'kind':kind})
    # Trend, momentum, participation, structure, risk: groups are displayed separately.
    ema20=i1['ema20']; ema50=i1.get('ema50')
    add('추세','20시간 이동평균 회복',price>ema20 and close[-2]<=ema20,'가격이 단기 평균선을 아래에서 위로 회복',8)
    add('추세','20·50시간 정배열',ema50 is not None and price>ema20>ema50,'현재가 > 20시간 평균 > 50시간 평균',7)
    add('추세','4시간 추세 동조',i4['close']>i4['ema20'] and i4['rsi']>=i4['rsi_prev'],'4시간 가격과 RSI가 상승 방향을 지지',8)
    add('모멘텀','RSI 상승 다이버전스',low[-1]<min(low[-9:-1]) and i1['rsi']>i1['rsi_3ago']+3,'가격은 8시간 저점을 낮췄으나 RSI는 3시간 전보다 개선(간이 신호)',7)
    add('모멘텀','RSI 중립구간 상향',45<=i1['rsi']<=65 and i1['rsi']>i1['rsi_prev'],'과매수 전 구간에서 RSI 상승',6)
    add('모멘텀','MACD 양전환',i1['hist']>0 and i1['hist_prev']<=0,'MACD 히스토그램이 음수에서 양수로 전환',9)
    add('모멘텀','MACD 상승 가속',i1['hist']>i1['hist_prev']>0,'양의 MACD 히스토그램이 연속 확대',6)
    add('거래','거래대금 증가',i1['turnover_ratio'] is not None and 1.5<=i1['turnover_ratio']<=8,'직전 20시간 평균 대비 거래대금 1.5~8배',9)
    add('거래','상승봉 거래 집중',close[-1]>float(c1[-1]['opening_price']) and vol[-1]>statistics.mean(vol[-21:-1])*1.2,'상승 마감봉에 평균 이상의 거래대금 유입',6)
    add('가격구조','직전 10시간 고점 돌파',price>max(high[-11:-1]) and close[-2]<=max(high[-12:-2]),'완성봉 종가가 직전 10시간 고점을 새로 돌파',9)
    add('가격구조','저점 상승',min(low[-5:])>min(low[-10:-5]),'최근 5시간 저점이 이전 5시간 저점보다 높음',5)
    add('가격구조','볼린저 중심선 회복',price>=i1['bb_mid'] and close[-2]<i1['bb_mid'] and i1['bb_position']<.9,'볼린저 중심선을 회복했고 상단 과열 전',7)
    add('캔들','아래꼬리 매수 반응',i1['lower_wick_ratio']>=.45 and i1['candle_bullish'],'완성된 1시간 양봉에 긴 아래꼬리',5)
    atr_pct=i1['atr14']/price*100 if price else 0
    risks=[]
    def risk(cond,label,detail,severity):
        if cond: risks.append({'name':label,'why':detail,'severity':severity})
    risk(i1['rsi']>=72,'RSI 과열','단기 과매수 가능성이 커짐','high')
    risk(i1['rise_6h_pct']>=9 or change>=14,'급등 추격 위험','이미 크게 오른 상태에서 진입하면 손익비가 나빠질 수 있음','high')
    risk(price>i1['bb_upper']*1.025,'볼린저 상단 과열','평균에서 과도하게 멀어진 가격','medium')
    risk(atr_pct>=9,'높은 1시간 변동성','ATR이 가격의 9% 이상으로 손절 폭이 커질 수 있음','high')
    risk(i4['hist']<i4['hist_prev'] and i4['rsi']<i4['rsi_prev'],'4시간 흐름 악화','상위 시간대 모멘텀이 약해지는 중','medium')
    risk(i1['turnover_ratio'] is not None and i1['turnover_ratio']<.65,'거래 참여 부족','직전 평균 대비 거래대금이 낮음','medium')
    risk(price<=i1['recent_low']*1.005,'지지선 이탈 위험','최근 20시간 저점과 매우 가까움','medium')
    # No additional points beyond existing score: independent confirmation is informational.
    hits=[e for e in evidence if e['met']]
    groups={g:sum(e['met'] for e in evidence if e['group']==g) for g in ('추세','모멘텀','거래','가격구조','캔들')}
    summary=[]
    if hits: summary.append('긍정: '+', '.join(e['name'] for e in sorted(hits,key=lambda e:-e['weight'])[:3]))
    else: summary.append('긍정 신호 부족: 뚜렷한 추가 상승 근거가 확인되지 않음')
    if risks: summary.append('주의: '+', '.join(r['name'] for r in risks[:3]))
    else: summary.append('주의: 지정된 과열·변동성 경고는 미발생(위험이 없다는 뜻은 아님)')
    summary.append('해석: '+('서로 다른 영역에서 신호 동조' if sum(v>0 for v in groups.values())>=3 else '상승 근거가 일부 영역에 집중')+' · 예측이 아닌 완성봉 관찰')
    return {'evidence':evidence,'risks':risks,'groups':groups,'positive_count':len(hits),
            'high_risk_count':sum(r['severity']=='high' for r in risks),'summary':summary,
            'atr_pct':round(atr_pct,2),'method':'1h/4h 완성봉, RSI, MACD, EMA20/50, 거래대금, BB, ATR, 가격구조, 캔들. 일부 지표는 상관관계가 있으므로 독립 신호로 간주하지 않음.'}
