"""백업 — SQLite 온라인 스냅샷(VACUUM INTO) → NAS 전송, 세대 관리 (FR-19, 설계 §11.4)."""

import logging
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from ..config import Settings

log = logging.getLogger(__name__)

_NAME_RE = re.compile(r"^herongs-(\d{8})\.db$")


def run_backup(settings: Settings, today: datetime | None = None) -> Path | None:
    """당일 스냅샷 생성·전송 후 보관 기한 초과분 삭제. 대상 경로 반환 (AC-12)."""
    if not settings.backup_dir:
        log.info("backup_dir 미설정 — 백업 생략")
        return None
    today = today or datetime.now()
    dest_dir = Path(settings.backup_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"herongs-{today.strftime('%Y%m%d')}.db"

    # VACUUM INTO — 구동 중에도 일관된 스냅샷 (설계 §11.4)
    src = sqlite3.connect(settings.db_path)
    try:
        if dest.exists():
            dest.unlink()
        src.execute("VACUUM INTO ?", (str(dest),))
    finally:
        src.close()
    log.info("백업 완료: %s", dest)

    # 세대 관리: 최근 N일치만 보관 (DS220j는 스냅샷 기능 없음 → 전송 측에서 수행)
    cutoff = (today - timedelta(days=settings.backup_keep_days)).strftime("%Y%m%d")
    for f in dest_dir.iterdir():
        m = _NAME_RE.match(f.name)
        if m and m.group(1) < cutoff:
            f.unlink()
            log.info("보관 기한 초과 백업 삭제: %s", f.name)
    return dest
