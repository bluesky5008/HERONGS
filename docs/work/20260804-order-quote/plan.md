# 구현 계획 — 주문 보조 정보 (20260804-order-quote)

## 기준선

- 요구사항·설계: `requirements-design.md` v1 (승인 2026-08-04)
- 상위 기준선: `docs/work/20260725-stock-advisor/design.md` §4.1·§4.2 (승인 시 갱신 대상)

## 계획

- [x] **T1 TR 매핑·계좌 조회 확장** — `ka10004` TR_PATHS 추가, `deposit()`(미사용)을 `orderable_cash()`(ord_alow_amt)로 교체. FR-22 / 설계 §4.2
- [x] **T2 호가 파싱·quote 조립** — `OrderService.quote(code, with_account)`, 4개 조회 병렬 + 부분 실패 흡수. FR-20/21/22, NFR-07/08 / 설계 §4.1·§4.2
- [x] **T3 라우트** — `GET /api/stocks/{code}/quote?with_account=`. 설계 §4.1
- [x] **T4 백엔드 테스트** — 호가 파싱(1단 fpr 예외·절댓값·5단 절단), quote 응답, 부분 실패 200+errors, with_account=false
- [x] **T5 프론트** — `api.quote()`, OrderDialog 보조 정보 블록·가격 탭·3초 자동 갱신·중지 3종. FR-20~24, AC-13~17
- [x] **T6 검증·배포** — 컨테이너 pytest, tsc 빌드, `docker compose up -d --build`, 장중 실기 확인
- [x] **T7 문서** — 상위 design.md §4.1/§4.2 갱신, 상위 plan.md 후속 목록 반영

## 위험·선행 확인

- `deposit()`은 저장소 전체에서 호출부 0건임을 확인(2026-08-04) → 이름·반환 변경 안전
- 호가 1단은 `fpr` 접두어로 규칙이 다름 → T4에서 테스트로 고정 (설계 R-2)
- 자동 갱신 중지 로직 누락 시 방치 폴링 위험 → T5·AC-17에서 필수 확인 (설계 R-1)

## 검증 (2026-08-04)

실행: `docker run --rm -v .../backend:/app python:3.12-slim … pytest -q` → **74 passed**(기존 70 + 신규 4)
빌드·배포: `docker compose up -d --build` (멀티스테이지 tsc 빌드 통과) → healthy, 기동 후 오류 로그 0건
실데이터 확인: 운영 컨테이너에서 `OrderService.quote("005930")` 직접 호출 (13:43 장중)

```
현재가 230,500 (-3.76%) | 보유 0 | 주문가능 499,994,528 | 호가 13:43:49
  매도 232,500/16,515  232,000/12,854  231,500/11,235  231,000/25,043  230,500/17,299
  매수 230,000/62,001  229,500/76,189  229,000/110,916 228,500/107,060 228,000/154,873
  총 매도 160,950 / 매수 913,663 | errors: []
with_account=False → holding_qty·orderable_cash 모두 None, 호가는 정상
```

| 인수 조건 | 검증 방법 | 결과 | 증거 |
|---|---|---|---|
| AC-13 | 단위 + 실데이터 | **API 통과** / 화면 실기 미확인 | `test_quote_endpoint`, 위 실호출(현재가·주문가능금액·호가 5단 모두 반환) |
| AC-14 | 단위 + 실데이터 | **부분** — 보유 10주 경로는 단위 통과, 실계좌는 보유 0이라 "0 표시" 경로만 확인 | `test_quote_parses_orderbook_and_account`(holding_qty=10) |
| AC-15 | 코드 | **미확인** — 탭 핸들러 구현, 실기 확인 필요 | `OrderDialog.tsx` 호가 셀 `onClick` |
| AC-16 | 단위 | **통과** | `test_quote_absorbs_partial_failure`(orderbook만 null + errors, 나머지 정상) |
| AC-17 | 단위 + 코드 | **부분** — 갱신 1회가 계좌 TR을 부르지 않음은 통과, 3초 주기·중지 3종은 실기 미확인 | `test_quote_without_account_skips_account_trs`(호출 TR = ka10001·ka10004만) |

**미수행**: 폰 PWA에서의 화면 표시·탭 입력·자동 갱신 체감(AC-13 화면분/15/17) — 사용자 장중 확인 필요.

## 완료

- 변경 요약: `ka10004` TR 매핑, `deposit()`→`orderable_cash()`(ord_alow_amt), `OrderService.quote()`(4 TR 병렬·부분 실패 흡수·호가 5단 파싱), `GET /api/stocks/{code}/quote?with_account=`, PWA 주문창 보조 정보 블록·가격 탭 입력·3초 자동 갱신·중지 3종.
- 설계와 달라진 점(경미, 4.1 경로): **화면 비활성 중지**를 "일시중지 표시 + 수동 재개"가 아니라 **호출만 건너뛰고 복귀 시 자동 재개**로 구현. 화면이 보이지 않는 동안에는 표시가 의미 없고, 복귀 때 조작을 요구하지 않는 편이 낫다고 판단. 요구의 실질(비활성 중 호출 없음)은 충족.
- 리뷰에서 수정한 것: 확인 화면에서 "돌아가기"로 입력 단계에 복귀하면 방치 타이머가 이미 만료돼 즉시 멈춤이 되는 문제 → 복귀 시 `keepAlive()` 재설정.
- 남은 사항: 설계 Q-A(매도 가능 수량 = 보유 수량, 미체결 매도분 미차감) 미해결 — 보유 종목이 생기는 시점에 kt00018 응답에 주문가능수량 필드가 있는지 확인 후 반영.
