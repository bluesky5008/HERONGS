"""SQLite 엔진·세션·setting 헬퍼 (설계 §3, NFR-06)."""

from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .models import Base, Setting

_engine = None
SessionLocal: sessionmaker | None = None


def init_db(db_path: Path | str):
    """엔진 생성 + 테이블 생성. 앱 기동 시 1회 호출."""
    global _engine, SessionLocal
    if isinstance(db_path, str) and db_path != ":memory:":
        db_path = Path(db_path)
    kwargs: dict = {"connect_args": {"check_same_thread": False}}
    if isinstance(db_path, Path) and str(db_path) != ":memory:":
        db_path.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{db_path}"
    else:
        # 인메모리는 스레드 간 커넥션 공유 필요 (테스트·TestClient)
        url = "sqlite:///:memory:"
        kwargs["poolclass"] = StaticPool
    _engine = create_engine(url, **kwargs)
    Base.metadata.create_all(_engine)
    SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def get_engine():
    return _engine


def get_setting(session: Session, key: str, default: str | None = None) -> str | None:
    row = session.get(Setting, key)
    return row.value if row else default


def set_setting(session: Session, key: str, value: str) -> None:
    row = session.get(Setting, key)
    if row:
        row.value = value
    else:
        session.add(Setting(key=key, value=value))
    session.commit()


def get_setting_float(session: Session, key: str, default: float) -> float:
    v = get_setting(session, key)
    try:
        return float(v) if v is not None else default
    except ValueError:
        return default
