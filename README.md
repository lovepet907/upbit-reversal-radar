# 업비트 상승 전환 레이더

PC 없이 GitHub Actions가 업비트 KRW 종목의 **마감된 1시간봉·4시간봉**을 수집하고, 기술적 지표 기반 TOP 10을 계산합니다. `index.html`은 `data/latest.json`을 읽어 표시합니다.

## 휴대전화로 설치하기

1. GitHub의 `upbit-reversal-radar` 저장소에 이 ZIP의 **파일과 폴더 구조 그대로** 올립니다. 모바일 GitHub 웹에서 폴더 업로드가 불편하면 ZIP을 풀고 GitHub 웹 편집기로 파일별 생성하세요. 특히 `.github/workflows/analyze.yml` 경로를 정확히 지켜야 합니다.
2. 저장소의 **Actions** 탭에서 **Upbit Hourly Analysis**를 열고 **Run workflow**를 눌러 최초 실행합니다. 몇 분 이상 걸릴 수 있습니다.
3. **Actions** 로그에서 성공 여부를 확인하고 `data/latest.json`이 생성되었는지 확인합니다.
4. **Settings → Pages → Build and deployment → Deploy from a branch → main / (root) → Save**를 선택합니다.
5. 잠시 후 `https://<GitHub아이디>.github.io/upbit-reversal-radar/` 주소로 접속합니다.

## 동작

- GitHub Actions: 매시 12분(UTC 기준)에 실행 **요청**됩니다. GitHub 일정 작업은 지연되거나 누락될 수 있으며, 비활성 공개 저장소에서는 자동 비활성화될 수 있습니다.
- Upbit API: 공개 API 키 불필요. 동시 요청 3개, 전역 호출 간격 0.42초, HTTP 429/일시 장애 시 재시도.
- 거래대금 24시간 1억 원 미만은 기본 분석 대상에서 제외합니다. 이는 **KRW 마켓 목록 전체를 탐색**하되 저유동성 종목을 분석에서 제외하는 정책입니다. 모든 KRW 종목을 분석하려면 `analyzer.py`의 `MIN_24H_KRW = 0`으로 바꾸세요.
- 점수는 RSI, MACD, 볼린저밴드, 거래대금, 캔들 형태 및 과열 필터를 합산한 **휴리스틱 점수**로, 상승 확률을 뜻하지 않습니다.
- 분석이 실패하면 이전 `data/latest.json`을 보존합니다. 화면에 마지막 성공 시각 및 오래된 데이터 경고가 표시됩니다.
- **공개 저장소 및 Pages는 공개**입니다. 계좌 정보, API 비밀키, 개인정보를 넣지 마세요.

## 주의

투자 추천이나 수익 보장이 아닙니다. 거래량 급증은 단순 1시간 거래대금/직전 20봉 평균 비율로 정의합니다. 업비트 캔들은 거래가 없는 시간에 생성되지 않을 수 있으므로, 지표는 수집된 거래 발생 봉 기준입니다. 화면의 지지·저항은 최근 20개 1시간봉 고저점 참고값이며 주문 가격이 아닙니다.
