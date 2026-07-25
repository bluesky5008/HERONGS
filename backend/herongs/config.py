"""설정 로딩 (.env) — 비밀 정보는 여기서만 다룬다 (NFR-01)."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REAL_BASE = "https://api.kiwoom.com"
MOCK_BASE = "https://mockapi.kiwoom.com"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="HERONGS_", extra="ignore"
    )

    # 거래 모드: 실계좌는 명시적 전환으로만 (NFR-02)
    trading_mode: str = "mock"  # mock | real

    kiwoom_appkey: str = ""
    kiwoom_secretkey: str = ""
    account_no: str = ""

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    pin: str = ""  # PWA 세션 인증 PIN (§7). 빈 값이면 인증 비활성(로컬 개발용)
    db_path: Path = Path("data/herongs.db")

    # 유량 제한 기본값 (설계 §10 Q-03 방침) — setting 테이블로 재정의 가능
    rate_global_per_sec: float = 5.0
    rate_per_tr_per_sec: float = 1.0

    scan_interval_min: int = 10
    recommend_top_n: int = 10

    # 주문 가드레일 (NFR-02, FR-15)
    max_order_amount: int = 5_000_000  # 1회 주문 금액 상한 (원)
    daily_order_limit: int = 20_000_000  # 일일 누적 주문 상한 (원)

    # 실시간 등록 한도 (Q-02: 실측 후 보정)
    ws_max_subscriptions: int = 90

    # 백업 (FR-19): NAS 마운트 경로 (예: \\DS220j\backup\herongs). 빈 값이면 백업 생략
    backup_dir: str = ""
    backup_keep_days: int = 14

    @property
    def api_base(self) -> str:
        return REAL_BASE if self.trading_mode == "real" else MOCK_BASE

    @property
    def ws_url(self) -> str:
        host = "api.kiwoom.com" if self.trading_mode == "real" else "mockapi.kiwoom.com"
        return f"wss://{host}:10000/api/dostk/websocket"


def load_settings() -> Settings:
    return Settings()
