# 업비트 상승 전환 레이더 V2

## 휴대전화로 업그레이드

기존 `lovepet907/upbit-reversal-radar` 저장소는 유지합니다.

1. ZIP 압축을 풀고 `analyzer.py`, `index.html` 두 파일을 기존 저장소의 **최상위 경로**에 각각 업로드하여 같은 이름으로 교체합니다. GitHub 웹 UI에서 같은 파일명을 업로드할 때 변경 내용을 확인하고 Commit합니다.
2. **반드시** `.github/workflows/analyze.yml`도 ZIP의 새 파일로 교체하세요. 관심종목 점수 기록을 위해 `data/history.json`까지 자동 커밋하도록 변경되었습니다. GitHub에서는 폴더 경로가 `.github/workflows/analyze.yml`인지 확인하세요.
3. GitHub 저장소 → Actions → Upbit Hourly Analysis → Run workflow → Run workflow.
4. 실행이 성공하면 `data/latest.json`과 `data/history.json`이 모두 생성되는지 확인합니다. 기존 `latest.json`에 있던 종목별 기록은 소급 복구되지 않으며 업데이트 후부터 쌓입니다.
5. https://lovepet907.github.io/upbit-reversal-radar/ 를 새로고침합니다. Pages 배포에 몇 분이 걸릴 수 있습니다.

## 관심종목 1시간 모니터링
- TOP 10의 별표(☆) 또는 종목 검색으로 등록합니다. TOP 10 밖의 분석 성공 종목도 등록 가능합니다.
- `data/latest.json`의 `markets`에 분석 성공한 전체 종목의 최신 점수와 간략한 지표가 담깁니다.
- `data/history.json`에는 전체 분석 성공 종목의 점수·분석가가 최대 168회(약 7일)까지 보관됩니다.
- 1시간 주기 Actions 완료 후 새 점수가 반영되며, 대시보드는 5분마다 새 데이터를 확인합니다. 실제 갱신은 GitHub Actions 및 Pages 배포 지연에 영향을 받습니다.
- 관심종목 선택은 휴대전화 브라우저의 localStorage에 저장됩니다. 다른 기기·시크릿 모드에서는 공유되지 않으며 브라우저 데이터를 삭제하면 사라질 수 있습니다.
- 분석에서 제외되거나 실패한 종목은 이전 기록을 그대로 유지하고 최신 점수는 미분석으로 표시합니다.

## 기능
- 1시간·4시간 완성봉 RSI, MACD, 볼린저밴드, 거래대금, EMA 분석
- 최근 3개 완성 1시간봉의 MACD 골든크로스 감지
- 최근 6·12시간 급등, RSI 과열, 볼린저 상단 과열 감점
- ATR14와 최근 20봉 고저점으로 **관찰용** 진입 범위·목표·손절 참고값 산출
- 점수는 상승 확률이 아니며, 과거 데이터로 성과 검증하지 않았음

## 주의
- 거래소 API는 실행 시 네트워크가 필요하며 GitHub Actions에서 실행합니다. 대시보드는 자동 주문을 하지 않습니다.
- 제시 가격은 호가 단위에 맞춰 반올림한 주문가격이 아닙니다. 체결 가능성, 수수료, 슬리피지를 반영하지 않았습니다.
- 신호 일치도 `높음/보통/낮음`은 통계적 승률이나 신뢰구간이 아닙니다.
- 새 워크플로는 `git add data/latest.json data/history.json`으로 두 데이터 파일을 함께 업데이트합니다.
