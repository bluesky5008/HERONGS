# 구현 계획 — HERONGS (작업-ID: 20260725-stock-advisor)

- 기준선: requirements.md v1, design.md v1 (승인일 2026-07-25)
- 작성일: 2026-07-25
- 상태 표기: `[ ]` pending / `[~]` in progress / `[x]` completed

## 환경 확인 (2026-07-25)

- Python 3.12.13 (uv 관리, `C:\Users\hippo\AppData\Roaming\uv\python\cpython-3.12.13-windows-x86_64-none\python.exe`) — 설계 스택과 일치
- Node.js/npm **미설치** → WU-12(PWA) 빌드·실행 검증 불가. 코드는 작성 가능, 빌드 검증은 Node 설치 후.
- Docker **미설치** → WU-13 배포 검증(AC-11) 불가. 구성 파일 작성은 가능.
- 키움 모의투자 appkey/secretkey 미보유 상태(.env 없음) → 실 API 통합 테스트(AC-01)는 키 발급 후. 단위 테스트는 목(mock) 기반.

## 작업 단위

### [x] WU-01 프로젝트 스캐폴딩·설정·로깅

- 목표: backend 패키지 구조, pyproject.toml, .env 로딩 설정, 로깅(키 마스킹)
- 관련 요구사항: NFR-01, NFR-05 / 설계 §1, §7
- 변경 대상: `backend/` 신규
- 검증: venv 생성, 의존성 설치, `pytest` 동작
- 완료 조건: 빈 FastAPI 앱 기동 가능, 설정 로드 테스트 통과

### [x] WU-02 데이터 모델

- 목표: SQLAlchemy 모델 11개 테이블 (설계 §3) + DB 초기화
- 관련 설계: §3 데이터 모델
- 의존성: WU-01
- 검증: create_all 후 테이블 존재 확인 테스트

### [x] WU-03 KiwoomClient

- 목표: 토큰 발급/갱신/폐기(au10001/au10002), 모의/실전 도메인 전환, 토큰버킷 스로틀(전역 5/s + TR당 1/s, setting 조정 가능), 연속조회(cont-yn/next-key), 오류코드별 백오프(1700/1701/1702, §6)
- 관련 요구사항: FR-01, FR-02, NFR-03 / 설계 §2, §6, §10(Q-03 방침)
- 의존성: WU-01
- 위험: 실제 API 검증은 키 발급 후 (AC-01 미수행으로 기록)
- 검증: 목 서버 기반 단위 테스트 — 토큰 갱신, 스로틀 대기, 1700 백오프, 연속조회 병합

### [x] WU-04 IndicatorEngine

- 목표: 이동평균, 이격도, 거래량 배율, 정배열 판정 등 순수 함수 모듈
- 관련 설계: §2 IndicatorEngine, 부록 B
- 의존성: 없음 (순수 함수)
- 검증: 지표별 단위 테스트

### [x] WU-05 ScoringEngine + 의견 판정

- 목표: Profile 플러그인 인터페이스, 장기/스윙/단타 3개 프로파일(부록 B 가중치, setting 로드), 시장 국면 보정, §5.6 판정 4단계(오버라이드 → 점수 매핑 → 히스테리시스 → 국면 보정)
- 관련 요구사항: FR-04~07, FR-14 / 설계 §2, §5.6, 부록 B
- 의존성: WU-02, WU-04
- 검증: 판정 규칙 단위 테스트 (오버라이드 우선, 히스테리시스 경계 3점, 하락 국면 +10)

### [x] WU-06 Collector (깔때기 스캔)

- 목표: 랭킹 TR 5종 + 조건검색(ka10172) 후보 수집 → 위생 필터(FR-12) → 상세 조회 → daily_price 적재(증분)
- 관련 요구사항: FR-03, FR-10, FR-12, FR-13(일반 실행), NFR-06 / 설계 §5.1
- 의존성: WU-02, WU-03
- 검증: 목 API 기반 — 후보 합집합·중복 제거·필터 탈락 테스트 (AC-07 단위 수준)

### [x] WU-07 RecommendationService + 성과 추적

- 목표: 스캔 결과 → 전략별 추천 저장(근거 JSON), 개별 종목 3관점 의견(§5.2), 1/5/20 영업일 경과 수익률 배치(§5.5), 적중률 리포트
- 관련 요구사항: FR-04~07, FR-16 / 설계 §5.2, §5.5
- 의존성: WU-05, WU-06
- 검증: 추천 저장·성과 계산 단위 테스트 (AC-02/03/09 단위 수준)

### [x] WU-08 OrderService (2단계 주문)

- 목표: preview(예상금액·비중·손절/목표가·가드레일) → confirm(preview_id, TTL 60초, 1회 사용) → kt10000/kt10001, 미체결·정정·취소, order_log 기록
- 관련 요구사항: FR-08, FR-09, FR-15, NFR-02, NFR-05 / 설계 §5.3, §7
- 의존성: WU-02, WU-03
- 위험: 주문 안전장치 — preview 우회 경로가 없어야 함 (AC-04)
- 검증: 가드레일 차단(AC-10), TTL 만료, preview_id 재사용 거부, confirm 없이 전송 불가 테스트

### [x] WU-09 REST API Layer

- 목표: §4.2 엔드포인트 전체 + PIN 세션 인증(§7)
- 관련 설계: §4.2, §7
- 의존성: WU-07, WU-08
- 검증: FastAPI TestClient 통합 테스트

### [x] WU-10 Scheduler + Notifier + 브리핑

- 목표: 휴장일·장 운영시간 인지 주기 제어(NFR-04), 장전(08:30)/마감 후 브리핑(FR-17), 텔레그램 발송·알림 이력(FR-11), 기동/종료 heartbeat(§11.5)
- 관련 요구사항: FR-11, FR-17, NFR-04 / 설계 §2, §11.5
- 의존성: WU-07
- 검증: 장중/장외 판정 단위 테스트, Notifier 목 발송 테스트

### [x] WU-11 RealtimeGateway

- 목표: WebSocket 접속·로그인·재접속, 조건검색 실시간(ka10173/10174), 0B/0D 구독→판정→해제(§5.4)
- 관련 요구사항: FR-13 / 설계 §5.4, §6
- 의존성: WU-03, WU-05
- 위험: Q-02(동시 등록 한도) 미확정 — 구독 즉시 해제 설계로 완화, 한도는 설정값
- 검증: 목 WS 서버로 재접속·재등록 테스트

### [x] WU-12 PWA 프론트엔드

- 목표: React+TS+Vite+PWA — 대시보드(추천 3탭+국면), 종목 분석, 주문 확인 다이얼로그, 포트폴리오, 성과 리포트, 설정(조건식 매핑)
- 관련 요구사항: D-04, AC-05 / 설계 §1, §4.2
- 의존성: WU-09. **환경 차단: Node 미설치** → 코드 작성까지, 빌드·모바일 뷰포트 검증(AC-05)은 Node 설치 후
- 검증: `npm run build` 성공 + 모바일 뷰포트 수동 확인 (차단 시 미수행 기록)

### [x] WU-13 배포·백업 구성

- 목표: Dockerfile, docker-compose.yml(restart, 헬스체크, 볼륨), 백업 배치(VACUUM INTO → SMB 전송, 14일 보관, 실패 시 텔레그램 경고)
- 관련 요구사항: FR-18, FR-19 / 설계 §11
- 의존성: WU-01(백업 배치는 WU-10 스케줄러에 등록)
- **환경 차단: Docker 미설치** → 구성 파일 작성까지, AC-11/12 검증은 Docker 설치 후
- 검증: compose config 문법 검증(차단 시 미수행 기록)

## 수행 순서

WU-01 → 02 → 03 → 04 → 05 → 06 → 07 → 08 → 09 → 10 → 11 → 13(파일 작성) → 12(파일 작성)

## 위험 요약

| 위험 | 완화 |
|---|---|
| 키움 API 키 미보유 → 실 API 검증 불가 | 목 기반 단위 테스트로 로직 검증, AC-01/04/08은 키 발급 후 모의 도메인에서 수행 |
| 유량 제한 수치 미확정 (Q-03) | 이중 스로틀 기본값 + setting 조정 (설계 §10 방침) |
| Node/Docker 미설치 | 코드·구성 작성까지 완료, 빌드·배포 검증은 후속 작업으로 기록 |

## 검증 기록 (2026-07-25)

실행 명령: `backend> .venv\Scripts\python -m pytest -q` → **62 passed** (0.71s)
기동 확인: `uvicorn herongs.main:app --port 8123` → `GET /healthz` 200, `GET /api/regime` 200

| AC | 상태 | 증거 |
|---|---|---|
| AC-01 | **통과** (2026-07-25 실검증) | 모의 도메인에서 au10001 토큰 발급 → 005930 분석 E2E 성공: kt00018·ka10131(4페이지 연속조회)·ka10001·ka10081 전부 200, 일봉 600건 적재(2024-02-02~2026-07-24), 3관점 의견 저장. TR당 1초 스로틀 동작 확인(로그 타임스탬프), 유량 오류(1700/1701) 미발생 |
| AC-02 | **통과** (2026-07-28 실검증) | 단위: test_run_scan_saves_recommendations_with_rationale. 실운영: 07-27·07-28 이틀간 장중 자동 스캔 — 추천 498건 저장(근거 JSON 포함, long 340/swing 158), 신규 추천 텔레그램 50건 전량 발송(sent=1). 주말(07-26)·장외 자동 스캔 없음 → 휴장·장시간 인지(NFR-04) 실확인 |
| AC-03 | 단위 검증 | test_recommendation.py::test_opinions_saved_and_stop_loss_alerts — 3관점 의견+근거, test_api.py 분석 API |
| AC-04 | **통과** (2026-08-03 실검증) | 단위: test_orders.py::test_confirm_requires_valid_preview, test_api.py::test_confirm_without_preview_via_api — confirm이 유일한 전송 경로. **실주문 E2E(모의계좌)**: 한국금융지주(071050) 1주 매수 — preview(예상금액·비중 0.04%·손절 190,000·목표 220,000 표시) → confirm → kt10000 접수(주문번호 0001459, 08:48) → 체결 → 잔고·보유 의견(FR-07) 반영, 미체결 없음 확인. 전 과정 폰 PWA(Tailscale 경유)에서 수행, order_log 기록 완비. **잔여 소검증도 완결(2026-08-04 12:43~12:45)**: ① 미체결 생성 — 119850 100주 @35,000 지정가 매수 접수(0109956) ② **정정** — 1차 시도는 키움 거부(RC4027 상/하한가 오류)가 502+사유로 표시(같은 날 새벽 수정한 핸들러 실전 첫 작동), @30,000으로 재정정 접수(0110028) ③ **취소** — 정정 후 신규 주문번호로 취소 접수(0110036), ka10075 미체결 조회 결과 0건으로 반영 확인 ④ **매도 E2E** — 한국금융지주(071050) 1주 @193,500 매도 접수(0110277) → 체결 → 보유 0·예수금 반영 확인. order_log 4건 전부 submitted 기록, API 응답 200(정정 1차만 502) |
| AC-05 | **통과** (2026-07-26 실기기 확인) | `npm run build` 성공(tsc 포함), Docker 컨테이너 static 서빙, 핸드폰(같은 Wi-Fi)에서 접속·렌더 확인. 접속 장애 2건 해결: ① Hyper-V 동적 포트 예약의 8000 점유 → 영구 예약 ② 방화벽 Private 전용 규칙이 WSL2 인바운드 경로와 미매칭 → Any 프로파일. 주문 확인 흐름의 모바일 검증은 AC-04 장중 E2E에서 함께 수행 |
| AC-06 | 단위 검증 + 채널 실검증 | 손절 오버라이드(test_scoring.py::test_override_stop_loss_beats_score) 단위 통과. 텔레그램 채널 실검증 완료(2026-07-25): sendMessage 테스트 + 기동 heartbeat 자동 발송 수신(alert_log sent=1, @HERONGS_ALARM_BOT → chat 8366481238). 손절 이벤트 실발송은 보유 종목 발생 후 확인 |
| AC-07 | 단위 검증 | test_collector.py::test_scan_end_to_end_excludes_halted, test_hygiene_filter_drops_flagged_and_illiquid |
| AC-08 | **통과** (2026-08-03 실검증) | 단위: test_realtime.py::test_refresh_conditions_upserts_preserving_mapping, test_collector.py::test_condition_source_feeds_candidates. **실 HTS 연동**: [0150]에서 HERONGS_LONG/SWING/SCALP 3식 작성·서버 저장(부록 A 기반, 공식 도움말 대조) → 앱 설정에서 목록 조회(CNSRLST)·전략 매핑(enabled=1) → 매핑 후 장중 스캔 정상 동작(08-03 추천 12건) |
| AC-09 | 부분 실검증 (2026-07-28) | 단위: test_evaluate_performance_and_report. 실운영: 1일 경과 수익률 187건 자동 평가(평균 -3.61%), 적중률이 마감 브리핑에 포함 발송(07-28: long 23.2%, swing 38.7%). 5/20영업일 호라이즌은 시간 경과 후 자동 평가 예정 |
| AC-10 | 단위 검증 | test_orders.py::test_preview_blocks_over_limit(사유 포함), test_api.py::test_order_guardrail_via_api(422+사유) |
| AC-11 | **통과** (타겟 0: 2026-07-29 / 타겟 1: 2026-07-30 재검증) | 타겟 0: `docker compose up -d --build` 기동 + 재부팅 무조작 자동 기동 확인(2026-07-29). 발견·수정 2건 — ① 컨테이너 UTC → TZ=Asia/Seoul ② Docker Desktop 로그인 자동 시작 실패 → StartupApproved 정리+시작 폴더 바로가기. **타겟 1(맥미니) 이관 후 재검증(2026-07-30)**: 5회 재부팅 반복 검증 끝에 무조작 통과 — 부팅 29초 만에 자동 로그인 → NAS 키체인 마운트(창 없음) → 컨테이너 기동 → heartbeat 발송. Docker 자동 시작·NAS 마운트 경쟁 등 발견 이슈와 해결은 deployment.md §8 수행 기록 참조 |
| AC-12 | **통과** (2026-07-30 완결) | 단위: test_backup_creates_snapshot_and_prunes. 타겟 0 로컬 백업 검증(07-29~30). **NAS 실전송 완결(2026-07-30)**: 맥미니에서 run_backup 실행 → NAS `backup/herongs` 공유에 `herongs-20260730.db`(83MB, VACUUM INTO) 생성 확인. 경로는 tailnet 경유 SMB(설계 변경 ⑥) — 컨테이너 `/backup` → 호스트 `/Volumes/backup/herongs` → NAS. 이후 매일 03:00 자동 |

## 운영 관찰 기록 (2026-07-28, 타겟 0 상시 구동 3일차)

DB(`data/herongs.db`)·컨테이너 상태·alert_log 실측 근거:

- 컨테이너 `herongs-backend`: 07-26 00:16 재생성 후 2일+ 연속 Up (healthy), 재시작·OOM 없음
- 스케줄러 KST 실동작: 아침 브리핑(08:30)·마감 브리핑(15:40)이 07-27(월)·07-28(화) 각 1건씩 발송(sent=1). 주말 07-26(일)에는 브리핑·자동 스캔 모두 없음 — 휴장 인지 정상 (07-26의 추천 2건은 00:31/21:49 수동 `POST /api/scan` 트리거)
- 장중 스캔: 07-27·07-28 09~15시에 new_recommendation 알림 각 25건, 발송 실패 0건
- 데이터 적재: daily_price 951,016행(1,772종목, ~2026-07-28), market_regime 3일 연속 bear 판정, 성과 평가(1일) 187건
- 백업: `backup/` 비어 있음 — 원인은 `HERONGS_BACKUP_DIR` 미설정으로 설계상 "생략" 분기(backup.py). 백업 실패·경고 아님. NAS 마운트 시(또는 타겟 0에서 `/backup` 지정 시) 활성화됨
- 미발송 1건: 07-25 22:45 info(sent=0) — 텔레그램 연동 완료 이전 시점의 기동 알림

## 설계와 달라진 점 (경미한 변경 — §4.1 기록)

1. **로컬 개발 Python 3.14 사용**: uv 관리 Python 3.12는 Windows 앱 제어 정책이 DLL 로드를 차단해 사용 불가. 코드와 Docker 이미지는 설계대로 3.12 유지(`python:3.12-slim`), 로컬 venv만 시스템 3.14.
2. **python-telegram-bot → httpx 직접 호출**: 발송은 Bot API POST 1건이므로 기존 의존성 httpx로 대체 (결정 사다리 5단계). 동작·요구사항 영향 없음.
3. **조건검색(ka10171/10172)은 REST가 아닌 WebSocket 경유**: 스펙 확인 결과 `/api/dostk/websocket` 전용(CNSRLST/CNSRREQ). 설계 §2의 RealtimeGateway 책임과 일치하며, Collector는 RealtimeGateway.run_condition을 주입받아 사용.
4. **조회성 API 3종 추가**: `POST /api/scan`(수동 스캔 트리거, AC-02 확인용), `GET /api/stocks/{code}/prices`(FR-06 차트 데이터), `POST /api/auth/login` + 관심종목 CRUD(FR-10, §7 PIN 세션). §4.2에 없던 항목이나 공개 계약 성격 변경 없음.
5. **장전 브리핑의 "예상체결 기반 갭 상위 종목" 제외**: 설계 §4.1 TR 매핑에 예상체결 TR이 없어 v1 브리핑은 전일 요약+국면+직전 스캔 요약으로 구성. 후속 작업으로 기록.
6. **NAS 백업 경로: 같은 LAN SMB → Tailscale 경유 SMB** (2026-07-30): 이관 중 NAS(DS220j)가 백엔드와 **다른 인터넷 회선**에 있음이 확인되어(공인 IP 상이) 설계 §11.4의 `smb://DS220j.local` 같은-LAN 가정을 폐기. NAS에 Synology Tailscale 패키지를 설치해 tailnet 합류(100.123.75.14) 후 SMB는 tailnet으로만 통신 — 포트 노출 금지 원칙(NFR-01)에 부합. 상세는 deployment.md §8.

## 남은 사항 (후속 작업)

- [ ] ~~키 발급~~·~~AC-01 실검증~~(2026-07-25 완료). 잔여: 유량 제한 실측(Q-03 → setting 보정), WS 동시 등록 한도 실측(Q-02), 조건검색 연속조회 필요 여부 확인
- [x] Node.js 24.18 설치·PWA 빌드·백엔드 서빙 검증 (2026-07-25) + 핸드폰 실기기 접속·렌더 확인 (2026-07-26, AC-05 통과)
- [x] Docker Desktop 설치·compose 기동·재부팅 자동 복구 확인 (AC-11 통과 — 2026-07-29 무조작 재부팅 자동 기동 재확인 완료)
- [x] ~~NAS(DS220j) SMB 마운트 후 백업 실전송 확인~~ (2026-07-30 완결 — AC-12 통과, tailnet 경유. deployment.md §8) `.env` 편집 시 주의: PS5.1 `Set-Content -Encoding utf8`은 BOM을 붙여 첫 변수를 깨뜨림 → BOM 없는 UTF-8로 저장할 것
- [x] 맥미니(타겟 1) 이관 — 2026-07-30 완료: 실행환경 구성 → `.env`+`data/` 이관 → 운영 기동 → 재부팅 무조작 검증(AC-11 재검증). 이관 중 발견·수정: 텔레그램 봇 토큰이 httpx INFO 로그에 노출 → 마스킹 등록 추가(커밋 6ffbc0c, 테스트 63건)
- [x] ~~장중 주문 E2E (AC-04)~~ (2026-08-03 매수 체결 + **2026-08-04 정정·취소·매도 실검증 완결** — 표의 AC-04 항목 참조). FR-08/09/15 실운영 검증 종료
- [x] ~~포트폴리오 보유 의견 라벨 스윙·단타 "S:" 표기 충돌~~ (2026-08-03 수정 — 다른 뷰와 동일한 PROFILE_LABELS 한글 표기로 통일)
- [x] ~~로그인 실패 시도 제한~~ (2026-08-03 완료 — DCR-001): 연속 5회 실패 시 300초 전역 잠금(429), 성공 시 카운터 리셋, PIN 비교 `secrets.compare_digest` 전환. 상태는 세션과 동일한 인메모리(`app.state.login_attempts`, 재기동 시 초기화). 검증: test_api.py::test_login_lockout_after_failures, test_login_success_resets_fail_count + 운영 컨테이너 실기 확인(오답 5회 → 6번째 429). design.md §7 보강, changes/DCR-001 기록
- [x] ~~주문 정정(modify) API 노출~~ (2026-08-03 완료 — FR-09 완성): `PUT /api/orders/{ord_no}` 라우트 추가(기구현 OrderService.modify 노출) + PWA 미체결 목록에 정정 UI(수량·가격 인라인 편집, 실패 사유 표시). 검증: test_api.py::test_order_modify_via_api(kt10002 모의 응답). 실기 정정은 AC-04 잔여 소검증과 함께 장중 확인 예정. ~~정정 시 상한 미적용~~ → 같은 날 보강 완료(DCR-002): modify() 진입부에서 1회 주문 금액 상한 직접 검사(422), 일일 누적은 이중 계산 문제로 미반영(근거는 DCR-002). 검증: test_orders.py::test_modify_blocks_over_limit, test_api.py::test_order_modify_via_api(422 분기 포함) — 테스트 67건
- [x] ~~scalp 실시간 파이프라인 배선~~ (2026-08-03 완료 — FR-13/§5.4, 승인 기준선 내 배선 작업): WU-11의 RealtimeGateway·ScalpSignalHandler는 기구현·기검증 상태였으나 앱에 연결되지 않았음. ① app.py에서 핸들러 생성·`on_real` 연결 + 종료 시 `realtime.stop()` ② 스케줄러에 1분 주기 `sync_scalp_realtime`(장중: scalp 조건식 ka10173 등록[멱등], 장외: 등록 폐기+접속 종료) ③ `register_realtime_condition` 멱등화, `stop()` 신설. 검증: test_realtime.py::test_sync_scalp_realtime_registers_in_hours_stops_after, test_api.py::test_scalp_handler_wired — 테스트 69건. 운영 확인: scalp_realtime_job 1분 주기 정상 실행(장외 no-op). **실기 부분 검증(2026-08-04)**: 장 시작 직후 09:00:07 WS 접속·로그인 성공(컨테이너 01:08 기동 + 1분 주기 → 09:00:07은 scalp 잡이 트리거한 것으로 특정), 이후 12:45까지 3시간 45분 무중단(재접속·수신종료·잡 실패 0건, 잡 696회 실행). **미검증 잔여**: 조건 편입 이벤트 수신 → 0B/0D 구독 → 신호 알림 경로(당일 HERONGS_SCALP 편입 종목이 없었던 것으로 추정 — alert_log에 scalp_signal 0건). 알려진 한계: 장중에 조건식 매핑을 해제해도 당일 마감 전까지는 등록 유지(동기화는 추가만 수행)
- [x] ~~KiwoomError가 API 응답에서 500으로 노출~~ (2026-08-04 수정 — 경량 경로): 2026-08-04 새벽 장전 매수 시도에서 발견 — 키움 모의서버 거부(RC4057 모의투자 장시작전)가 confirm 라우트에서 처리되지 않아 Internal Server Error로 표시(order_log에는 failed로 정상 기록, 주문 미접수). app.py에 KiwoomError 전역 예외 핸들러 추가 → 502 + 거부 사유(return_msg) 반환, 키움 호출 전체 라우트에 일괄 적용. 검증: test_api.py::test_kiwoom_rejection_returns_502_with_reason — 테스트 70건
- [ ] **WS 응답 라우팅 경쟁 가능성**(2026-08-04 검증 중 코드 리뷰로 발견, 미발생): `_recv_loop`이 응답을 `trnm` 키 하나로만 대기 future에 매칭한다. 조건검색 실시간 등록(CNSRREQ search_type=1)과 일반 실행(search_type=0)이 같은 `trnm`을 쓰므로, `run_condition` 대기 중에 실시간 등록 응답이 도착하면 엉뚱한 payload로 future가 풀릴 수 있다. 현재는 등록이 멱등(장 시작 직후 1회)이라 충돌 창이 매우 좁아 실제 발생 이력 없음. 수정 시 seq 등 식별자를 포함한 매칭 키 사용 검토
- [ ] 장전 브리핑 갭 상위 종목: 예상체결 TR 확인·매핑 후 추가 (설계 §4.1 갱신 필요)
- [x] 텔레그램 봇 생성·연동 (2026-07-25 완료: @HERONGS_ALARM_BOT, heartbeat 실수신 확인). 강제 종료 시에는 종료 알림이 발송되지 않음(정상 종료에서만 발송) — 운영 시 참고
