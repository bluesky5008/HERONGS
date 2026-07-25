# HERONGS 배포 설정·검증 기록

- 관련 설계: [design.md §11 배포·운영](work/20260725-stock-advisor/design.md) (ADR-06, FR-18/19)
- 검증 상태 원장: [plan.md 검증 기록](work/20260725-stock-advisor/plan.md)
- 최종 갱신: 2026-07-25

## 1. 배포 구조 요약

| 단계 | 타겟 | 상태 |
|---|---|---|
| 1차 | 사용자 노트북 (Windows 11) | **환경 구성 진행 중** (이 문서의 기록 대상) |
| 2차 | 미니PC (Ubuntu Server, 구매 시기 미정) | 대기 — 이전 절차는 §6 |
| 상시 | NAS DS220j | 백업 저장소 전용 (실행 환경 아님) |

단일 컨테이너(`herongs-backend`) 안에 FastAPI + 스케줄러 + WebSocket + PWA 정적 서빙이 모두 들어간다.
상태는 전부 호스트의 `./data/`(SQLite)와 `.env`에 외부화되어 있어 **타겟 이전 = 이 두 개 복사**다.

## 2. 노트북(1차 타겟) 환경 설정 이력 — 2026-07-25

### 완료된 설정

| 항목 | 내용 | 비고 |
|---|---|---|
| Python 백엔드 | 시스템 Python 3.14 venv (`backend/.venv`), `pip install -e .[dev]` | uv 관리 3.12는 Windows 앱 제어 정책이 DLL 차단 → 사용 불가. **Docker 이미지는 설계대로 3.12** |
| Node.js | 24.18 LTS (winget `OpenJS.NodeJS.LTS`) | PWA 빌드용 |
| PWA 빌드 | `frontend> npm install && npm run build` → `dist/` | tsc 타입 검사 포함 통과, 아이콘·서비스워커 생성 |
| PWA 배포 | `dist/` → `backend/static/` 복사 | 백엔드가 `/`에서 정적 서빙. Docker 빌드에서는 멀티스테이지가 자동 수행 |
| 설정 파일 | 저장소 루트 `.env` (키움 모의투자 키, 텔레그램 토큰/chat_id) | **gitignore 처리 — 커밋 금지.** 템플릿은 `.env.example` |
| 텔레그램 | @HERONGS_ALARM_BOT ↔ chat_id 8366481238 | 기동 heartbeat 실수신 확인 (§11.5 장애 인지 규칙 가동) |

### 미설치 (다음 단계)

- **Docker Desktop** (+ WSL2) — AC-11 검증의 선행 조건. 설치 시 재부팅 필요 가능
- **Tailscale** — 외부(외출 중) 접속 경로. 포트포워딩은 금지(NFR-01)
- **NAS SMB 마운트** — 백업 전송 대상 경로(FR-19, AC-12)

## 3. 로컬(비 Docker) 실행 — 현재 사용 가능한 방법

```powershell
cd c:\git\finance
backend\.venv\Scripts\python -m uvicorn herongs.main:app --host 0.0.0.0 --port 8000
```

- 저장소 루트에서 실행해야 루트의 `.env`·`data/`를 사용한다.
- 기동 성공 시 텔레그램으로 "HERONGS 백엔드 기동" 메시지가 온다 (안 오면 장애로 간주 — §11.5).
- 같은 Wi-Fi의 핸드폰에서 `http://<노트북IP>:8000` 접속 → PWA 확인 (AC-05 실기기 확인).

## 4. Docker 배포 (AC-11 — 검증 대기)

```powershell
cd c:\git\finance
docker compose up -d --build
```

- [docker-compose.yml](../docker-compose.yml): `restart: unless-stopped`(재부팅 자동 복구), 헬스체크(`/healthz`), `./data` 볼륨, `.env` 주입
- [Dockerfile](../Dockerfile): 1단계 node:20에서 PWA 빌드 → 2단계 python:3.12-slim에 산출물 포함
- **AC-11 판정 기준**: `docker compose up -d` 한 번으로 기동 + 호스트 재부팅 후 자동 재기동
- 노트북 운영 수칙(설계 §11.3): 절전 해제, 덮개 닫아도 유지, Docker Desktop 자동 시작, Windows 업데이트 활성 시간을 장중으로 설정

## 5. 백업 (FR-19 / AC-12 — 검증 대기)

- 매일 03:00 스케줄러가 `VACUUM INTO` 스냅샷 → `HERONGS_BACKUP_DIR`에 `herongs-YYYYMMDD.db` 전송, 최근 14일 보관
- 백업 실패 시 텔레그램 경고 발송
- 남은 설정: DS220j SMB 공유를 노트북에 마운트하고 `.env`의 `HERONGS_BACKUP_DIR`(로컬 실행) 또는 `HERONGS_BACKUP_MOUNT`(compose)로 지정
- 스냅샷 생성·보관 로직은 단위 테스트로 검증됨. **실 NAS 전송 확인(AC-12)만 잔여**

## 6. 타겟 이전 절차 (노트북 → 미니PC)

1. 노트북: `docker compose down`
2. `data/` 디렉터리와 `.env` 파일을 미니PC로 복사
3. 미니PC(Ubuntu + Docker Engine): 저장소 clone → 복사한 `data/`·`.env` 배치 → `docker compose up -d --build`
4. Tailscale 설치·로그인, 핸드폰 PWA 주소를 새 Tailscale 주소로 변경
5. 백업 마운트 경로 재설정 후 다음날 백업 파일 생성 확인

## 7. 보안 체크리스트 (NFR-01/02)

- [x] `.env`는 gitignore — appkey/secretkey/토큰/계좌번호는 로컬에만
- [x] `.env.example`(커밋되는 템플릿)에는 실제 값을 넣지 않는다 ⚠️ 두 차례 실수 이력 있음 — 커밋 전 확인 필수
- [x] 실계좌 모드는 `.env`의 `HERONGS_TRADING_MODE=real` 명시 전환으로만 (기본 mock)
- [x] 로그에서 키·토큰·계좌번호 마스킹
- [ ] 인터넷 직접 노출 금지 — 포트포워딩 없이 Tailscale만 (Tailscale 설치 시 방화벽 규칙 함께 점검)
- [ ] PWA PIN 설정 (`HERONGS_PIN`) — 외부 접속 개통 전 필수
