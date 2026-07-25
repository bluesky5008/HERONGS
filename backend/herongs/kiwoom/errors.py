"""키움 API 오류 (설계 §6)."""

RATE_LIMIT_PER_TR = 1700  # API별 유량 초과 → 해당 TR만 백오프
RATE_LIMIT_GLOBAL = {1701, 1702}  # 전체/그룹 유량 초과 → 전역 백오프
RECURSION_LIMIT = 1687  # 재귀 호출 제한 → 재시도 없이 버그로 취급


class KiwoomError(Exception):
    def __init__(self, return_code: int, return_msg: str, tr_id: str = ""):
        self.return_code = return_code
        self.return_msg = return_msg
        self.tr_id = tr_id
        super().__init__(f"[{tr_id}] {return_code}: {return_msg}")

    @property
    def is_rate_limit(self) -> bool:
        return self.return_code == RATE_LIMIT_PER_TR or self.return_code in RATE_LIMIT_GLOBAL
