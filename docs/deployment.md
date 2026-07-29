# HERONGS 배포 설정·검증 기록

- 관련 설계: [design.md §11 배포·운영](work/20260725-stock-advisor/design.md) (ADR-06, FR-18/19)
- 검증 상태 원장: [plan.md 검증 기록](work/20260725-stock-advisor/plan.md)
- 최종 갱신: 2026-07-29

## 1. 배포 구조 요약

> **2026-07-29 변경**: 운영 기기를 **맥북(macOS)** 으로 확정. 기존 계획(Windows 노트북 → 미니PC 2단계 이관, DS220j 실행 검토)은 폐기. DS220j는 원설계대로 백업 전용.

| 단계 | 타겟 | 역할 | 상태 |
|---|---|---|---|
| **타겟 0** | 현재 개발 PC (Windows 11, c:\git\finance) | 개발 + 배포 구성 완성·검증 | 검증 완료 (AC-11 통과 2026-07-29) — 이관 후 개발 전용 복귀 |
| **타겟 1** | 맥북 (macOS) | 실운영 24시간 상시 구동 (모의투자 → 실계좌) | **이관 목표** — §6 절차로 이관 |
| 상시 | NAS DS220j | 백업 저장소 전용 (실행 환경 아님) | 대기 (맥북에 SMB 마운트 필요) |

**운영 방침**: 타겟 0에서 "복사만 하면 도는" 상태까지 검증 완료(AC-11). 맥북(타겟 1) 이관 후, 개발·수정은 타겟 0에서 하고 git으로 배포한다. Apple Silicon 맥북이면 Docker가 arm64 이미지를 네이티브 빌드하므로 교차 빌드 등 추가 작업은 없다(전 의존성 arm64 호환 확인됨, 2026-07-27).

단일 컨테이너(`herongs-backend`) 안에 FastAPI + 스케줄러 + WebSocket + PWA 정적 서빙이 모두 들어간다.
상태는 전부 호스트의 `./data/`(SQLite)와 `.env`에 외부화되어 있어 **타겟 이전 = 이 두 개 복사**다.

## 2. 타겟 0(개발 PC) 환경 설정 이력 — 2026-07-25

### 완료된 설정

| 항목 | 내용 | 비고 |
|---|---|---|
| Python 백엔드 | 시스템 Python 3.14 venv (`backend/.venv`), `pip install -e .[dev]` | uv 관리 3.12는 Windows 앱 제어 정책이 DLL 차단 → 사용 불가. **Docker 이미지는 설계대로 3.12** |
| Node.js | 24.18 LTS (winget `OpenJS.NodeJS.LTS`) | PWA 빌드용 |
| PWA 빌드 | `frontend> npm install && npm run build` → `dist/` | tsc 타입 검사 포함 통과, 아이콘·서비스워커 생성 |
| PWA 배포 | `dist/` → `backend/static/` 복사 | 백엔드가 `/`에서 정적 서빙. Docker 빌드에서는 멀티스테이지가 자동 수행 |
| 설정 파일 | 저장소 루트 `.env` (키움 모의투자 키, 텔레그램 토큰/chat_id) | **gitignore 처리 — 커밋 금지.** 템플릿은 `.env.example` |
| 텔레그램 | @HERONGS_ALARM_BOT ↔ chat_id 8366481238 | 기동 heartbeat 실수신 확인 (§11.5 장애 인지 규칙 가동) |
| WSL2 사전 조건 | BIOS 가상화(VT-x) 활성 확인, Windows 기능 활성화(가상 머신 플랫폼 + WSL, DISM) | 재부팅 후 반영 완료 |
| Docker Desktop | 4.83.0 (winget), 엔진 29.6.2 | 설치·기동 확인 완료 |
| Docker 배포 검증 | `docker compose up -d --build` 1회로 빌드(PWA 멀티스테이지 포함)·기동, 헬스체크 `healthy`, heartbeat 수신 | **AC-11 전반부 통과** (2026-07-25). 시간대 버그 발견·수정: 컨테이너 UTC → `ENV TZ=Asia/Seoul` (스케줄러 KST 필수) |
| Docker 자동 시작 | settings AutoStart=true + HKCU Run 키 + 시작 폴더 바로가기 | 1차 재부팅 테스트에서 Run 키 자동 시작 실패(StartupApproved 값 비정상 01 → 항목 제거) → 시작 폴더 바로가기 추가(이중화). 무조작 자동 시작 재확인 완료(2026-07-29, AC-11 통과) |
| 재부팅 자동 복구 (컨테이너) | 엔진 기동 후 5초 만에 `herongs-backend` 자동 재기동 → healthy, heartbeat 발송(23:58 KST) | **검증 완료** — `restart: unless-stopped` 동작. 잔여 리스크는 Docker Desktop 자동 시작뿐 |
| 포트 8000 영구 예약 | `netsh int ipv4 add excludedportrange protocol=tcp startport=8000 numberofports=1 store=persistent` (winnat 중지 상태에서) | **재부팅 후 Hyper-V 동적 예약 범위(7981-8080)가 8000을 점유 → 포트 게시 실패** 문제 해결(2026-07-26). Windows 전용 이슈 — 맥북(타겟 1)은 해당 없음 |
| 방화벽 인바운드 | "HERONGS PWA (TCP 8000)" 규칙 — **모든 프로파일(Any)** 허용 | 같은 Wi-Fi 핸드폰 접속용. Private 전용 규칙으로는 **차단됨** — Docker Desktop(WSL2) 인바운드가 Hyper-V 가상 스위치 경유라 Wi-Fi의 Private 프로파일과 매칭되지 않음. 프로파일 Any로 변경해 해결(2026-07-26, 폰 접속 확인). 외부 노출은 없음 — 공유기 뒤 사설망 + 포트포워딩 금지 원칙 유지 |

### 타겟 0에서 남은 단계

- ~~재부팅 무조작 자동 시작 재확인~~ (2026-07-29 완료 — AC-11 통과)
- ~~장중 스캔·알림 실검증~~ (AC-02 통과, 2026-07-28 — 07-27·28 이틀 운영 실측)
- 장중 모의 주문 E2E (AC-04) — 이관 전 타겟 0에서 수행하거나, 이관 후 맥북에서 수행 중 택일

Tailscale·NAS 마운트는 상시 구동 기기인 **타겟 1(맥북)에서 설정**하는 것이 기준이다(타겟 0에는 불필요).

## 3. 로컬(비 Docker) 실행 — 현재 사용 가능한 방법

```powershell
cd c:\git\finance
backend\.venv\Scripts\python -m uvicorn herongs.main:app --host 0.0.0.0 --port 8000
```

- 저장소 루트에서 실행해야 루트의 `.env`·`data/`를 사용한다.
- 기동 성공 시 텔레그램으로 "HERONGS 백엔드 기동" 메시지가 온다 (안 오면 장애로 간주 — §11.5).
- 같은 Wi-Fi의 핸드폰에서 `http://<호스트IP>:8000` 접속 → PWA 확인 (AC-05 실기기 확인).

## 4. Docker 배포 (AC-11 — 통과, 2026-07-29)

```powershell
cd c:\git\finance
docker compose up -d --build
```

- [docker-compose.yml](../docker-compose.yml): `restart: unless-stopped`(재부팅 자동 복구), 헬스체크(`/healthz`), `./data` 볼륨, `.env` 주입
- [Dockerfile](../Dockerfile): 1단계 node:20에서 PWA 빌드 → 2단계 python:3.12-slim에 산출물 포함
- **AC-11 판정 기준**: `docker compose up -d` 한 번으로 기동 + 호스트 재부팅 후 자동 재기동 — 타겟 0에서 통과(무조작 재부팅 재확인 2026-07-29). 맥북 이관 후 §6-A 7단계에서 동일 기준으로 재검증
- 상시 구동 운영 수칙(설계 §11.3)의 macOS 버전은 §6-A 4단계 참조

## 5. 백업 (FR-19 / AC-12 — 검증 대기)

- 매일 03:00 스케줄러가 `VACUUM INTO` 스냅샷 → `HERONGS_BACKUP_DIR`에 `herongs-YYYYMMDD.db` 전송, 최근 14일 보관
- 백업 실패 시 텔레그램 경고 발송
- 남은 설정: DS220j SMB 공유를 맥북에 마운트하고 `.env`의 `HERONGS_BACKUP_DIR`(로컬 실행) 또는 `HERONGS_BACKUP_MOUNT`(compose)로 지정 — §6-A 6단계
- 스냅샷 생성·보관 로직은 단위 테스트로 검증됨. **실 NAS 전송 확인(AC-12)만 잔여**. 타겟 0은 `HERONGS_BACKUP_DIR` 미설정으로 설계상 "생략" 동작 중(2026-07-28 확인)

## 6. 타겟 이전 절차

### 6-A. 타겟 0(개발 PC) → 타겟 1(맥북) — 다음 이관 목표

선행 조건: 타겟 0에서 AC-11 검증 완료(2026-07-29 충족). Windows 전용 준비 항목(포트 예약, 방화벽 프로파일, WSL2)은 맥북에서 전부 불필요하다.

1. **맥북 준비**: Docker Desktop for Mac 설치(설정에서 "Start Docker Desktop when you sign in" 활성화), `git --version`으로 Command Line Tools 설치, `git clone https://github.com/bluesky5008/HERONGS`. Node·Python 별도 설치 불필요(이미지 빌드 내 처리)
2. 타겟 0: 컨테이너 중지(`docker compose stop`) → `data/` 디렉터리와 `.env` 파일을 맥북 저장소 루트로 복사. **`.env`는 git 경유 금지**(실키 유출 실수 이력 2회) — AirDrop/USB 등으로 직접 전달
3. 맥북: `docker compose up -d --build` → `/healthz` 200 + 텔레그램 "백엔드 기동" heartbeat 수신 확인. 확인 즉시 **타겟 0 컨테이너는 정지 유지**(이중 구동 시 스케줄 알림·스캔 중복 발송)
4. **macOS 상시 구동 수칙**(설계 §11.3의 macOS 버전):
   - 시스템 설정 → 배터리: "전원 어댑터 연결 시 디스플레이가 꺼져 있을 때 자동으로 잠자지 않음" 켜기
   - 덮개 닫고 운영 시: `sudo pmset -c disablesleep 1`
   - 정전 후 자동 재시동: `sudo pmset -a autorestart 1`
   - macOS 자동 업데이트의 자동 재시동 끄기 → 업데이트는 장외 시간에 수동 적용
   - **FileVault 주의**: 켜져 있으면 재부팅 후 로그인 전까지 Docker 미기동. 무인 복구가 필요하면 자동 로그인(FileVault 해제 필요)과의 보안 트레이드오프를 결정할 것. 미결정 시 수칙: "재부팅은 사람이 있을 때만"
5. **Tailscale 개통**(상시 구동 기기이므로 여기서): 개통 전 `.env`에 `HERONGS_PIN` 설정 필수(§7 체크리스트) → Tailscale Mac 앱 설치·로그인 → 핸드폰에서 `http://<맥북 Tailscale 주소>:8000` PWA 접속 확인. 같은 Wi-Fi 로컬 접속은 macOS 방화벽 허용 프롬프트만 수락하면 됨
6. **NAS 백업 개통**: Finder에서 `smb://DS220j.local/<공유>` 연결(마운트 경로 `/Volumes/<공유명>`) + 로그인 항목에 추가(자동 마운트) → `.env`에 `HERONGS_BACKUP_MOUNT=/Volumes/<공유명>/herongs` 지정 → `docker compose up -d` 재기동 → 다음날 새벽 `herongs-YYYYMMDD.db` 생성 확인 (AC-12). 무인 재부팅까지 견고하게 하려면 로그인 항목 대신 autofs 구성(4단계 FileVault 결정과 묶어서 선택)
7. 재부팅 테스트: 맥북 재부팅 후 무조작으로 컨테이너 자동 기동 + heartbeat 수신 + NAS 마운트 살아있는지 확인
8. 이관 완료 후: 타겟 0은 개발 전용으로 복귀(상시 구동 안 함). 코드 변경은 git push → 맥북에서 `git pull && docker compose up -d --build`

이관 후 첫 거래일에 확인: 아침 브리핑(08:30)·장중 스캔 알림·마감 브리핑(15:40) 수신.

## 7. 보안 체크리스트 (NFR-01/02)

- [x] `.env`는 gitignore — appkey/secretkey/토큰/계좌번호는 로컬에만
- [x] `.env.example`(커밋되는 템플릿)에는 실제 값을 넣지 않는다 ⚠️ 두 차례 실수 이력 있음 — 커밋 전 확인 필수
- [x] 실계좌 모드는 `.env`의 `HERONGS_TRADING_MODE=real` 명시 전환으로만 (기본 mock)
- [x] 로그에서 키·토큰·계좌번호 마스킹
- [ ] 인터넷 직접 노출 금지 — 포트포워딩 없이 Tailscale만 (Tailscale 설치 시 방화벽 규칙 함께 점검)
- [ ] PWA PIN 설정 (`HERONGS_PIN`) — 외부 접속 개통 전 필수
