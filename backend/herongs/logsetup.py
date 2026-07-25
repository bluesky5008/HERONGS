"""로깅 설정 — 비밀 정보 마스킹 (NFR-01, 설계 §7)."""

import logging

_SECRETS: set[str] = set()


def register_secret(value: str) -> None:
    """로그에서 마스킹할 값 등록 (appkey/secretkey/토큰/계좌번호)."""
    if value and len(value) >= 4:
        _SECRETS.add(value)


class SecretMaskFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        masked = msg
        for s in _SECRETS:
            if s in masked:
                masked = masked.replace(s, "***")
        if masked is not msg:
            record.msg = masked
            record.args = ()
        return True


def setup_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    handler.addFilter(SecretMaskFilter())
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers[:] = [handler]
