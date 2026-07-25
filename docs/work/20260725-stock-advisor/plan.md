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
| AC-02 | 단위 검증 | test_recommendation.py::test_run_scan_saves_recommendations_with_rationale — 전략별 N개 이하 + 근거 |
| AC-03 | 단위 검증 | test_recommendation.py::test_opinions_saved_and_stop_loss_alerts — 3관점 의견+근거, test_api.py 분석 API |
| AC-04 | 단위 검증 | test_orders.py::test_confirm_requires_valid_preview, test_api.py::test_confirm_without_preview_via_api — confirm이 유일한 전송 경로, preview 필수 |
| AC-05 | 빌드·서빙 통과, 실기기 확인 대기 | Node 24.18 설치(2026-07-25) → `npm run build` 성공(tsc 타입 검사 포함), PWA 아이콘·서비스워커 생성, 백엔드 static 서빙에서 `/`·manifest·API 동일 오리진 200 확인. 핸드폰 실기기 뷰포트·홈 화면 설치 확인은 사용자 수행 필요 |
| AC-06 | 단위 검증 + 채널 실검증 | 손절 오버라이드(test_scoring.py::test_override_stop_loss_beats_score) 단위 통과. 텔레그램 채널 실검증 완료(2026-07-25): sendMessage 테스트 + 기동 heartbeat 자동 발송 수신(alert_log sent=1, @HERONGS_ALARM_BOT → chat 8366481238). 손절 이벤트 실발송은 보유 종목 발생 후 확인 |
| AC-07 | 단위 검증 | test_collector.py::test_scan_end_to_end_excludes_halted, test_hygiene_filter_drops_flagged_and_illiquid |
| AC-08 | 단위 검증 | test_realtime.py::test_refresh_conditions_upserts_preserving_mapping, test_collector.py::test_condition_source_feeds_candidates. 실 HTS 연동은 키 발급 후 |
| AC-09 | 단위 검증 | test_recommendation.py::test_evaluate_performance_and_report — 1/5/20일 수익률·적중률 |
| AC-10 | 단위 검증 | test_orders.py::test_preview_blocks_over_limit(사유 포함), test_api.py::test_order_guardrail_via_api(422+사유) |
| AC-11 | **미수행** | Docker 미설치. Dockerfile/compose 작성 완료(restart·healthcheck 포함), 검증은 Docker 설치 후 |
| AC-12 | 단위 검증 | test_scheduler_notifier.py::test_backup_creates_snapshot_and_prunes(VACUUM INTO·14일 보관). 실 NAS 전송은 마운트 후 |

## 설계와 달라진 점 (경미한 변경 — §4.1 기록)

1. **로컬 개발 Python 3.14 사용**: uv 관리 Python 3.12는 Windows 앱 제어 정책이 DLL 로드를 차단해 사용 불가. 코드와 Docker 이미지는 설계대로 3.12 유지(`python:3.12-slim`), 로컬 venv만 시스템 3.14.
2. **python-telegram-bot → httpx 직접 호출**: 발송은 Bot API POST 1건이므로 기존 의존성 httpx로 대체 (결정 사다리 5단계). 동작·요구사항 영향 없음.
3. **조건검색(ka10171/10172)은 REST가 아닌 WebSocket 경유**: 스펙 확인 결과 `/api/dostk/websocket` 전용(CNSRLST/CNSRREQ). 설계 §2의 RealtimeGateway 책임과 일치하며, Collector는 RealtimeGateway.run_condition을 주입받아 사용.
4. **조회성 API 3종 추가**: `POST /api/scan`(수동 스캔 트리거, AC-02 확인용), `GET /api/stocks/{code}/prices`(FR-06 차트 데이터), `POST /api/auth/login` + 관심종목 CRUD(FR-10, §7 PIN 세션). §4.2에 없던 항목이나 공개 계약 성격 변경 없음.
5. **장전 브리핑의 "예상체결 기반 갭 상위 종목" 제외**: 설계 §4.1 TR 매핑에 예상체결 TR이 없어 v1 브리핑은 전일 요약+국면+직전 스캔 요약으로 구성. 후속 작업으로 기록.

## 남은 사항 (후속 작업)

- [ ] 키움 모의투자 appkey/secretkey 발급 후: AC-01 실검증, 유량 제한 실측(Q-03 → setting 보정), WS 동시 등록 한도 실측(Q-02), 조건검색 연속조회 필요 여부 확인
- [x] Node.js 24.18 설치·PWA 빌드·백엔드 서빙 검증 (2026-07-25). 남은 것: 핸드폰 실기기에서 뷰포트·홈 화면 설치 확인 (AC-05 완결 조건)
- [ ] Docker Desktop 설치 후: `docker compose up -d --build`, 재부팅 자동 기동 확인 (AC-11)
- [ ] NAS(DS220j) SMB 마운트 경로 설정 후: 백업 실전송 확인 (AC-12)
- [ ] 장전 브리핑 갭 상위 종목: 예상체결 TR 확인·매핑 후 추가 (설계 §4.1 갱신 필요)
- [x] 텔레그램 봇 생성·연동 (2026-07-25 완료: @HERONGS_ALARM_BOT, heartbeat 실수신 확인). 강제 종료 시에는 종료 알림이 발송되지 않음(정상 종료에서만 발송) — 운영 시 참고
