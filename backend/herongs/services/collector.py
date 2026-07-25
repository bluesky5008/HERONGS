"""Collector — 깔때기 스캔 1단계 + 시세 적재 (FR-03/10/12/13, NFR-06, 설계 §5.1)."""

import logging
from datetime import date, datetime

from sqlalchemy import func, select

from ..config import Settings
from ..kiwoom import KiwoomClient
from ..models import ConditionMap, DailyPrice, Instrument, MarketRegime
from ..scoring import Candidate, classify_regime
from ..utils import pnum, price

log = logging.getLogger(__name__)

# 깔때기 1차 랭킹 TR (설계 §4.1). 관리종목·우선주는 요청 조건에서 1차 배제.
RANKING_CALLS = [
    ("ka10023", {"mrkt_tp": "000", "sort_tp": "2", "tm_tp": "2", "trde_qty_tp": "50",
                 "tm": "", "stk_cnd": "1", "pric_tp": "8", "stex_tp": "1"}, "trde_qty_sdnin"),
    ("ka10032", {"mrkt_tp": "000", "mang_stk_incls": "0", "stex_tp": "1"}, "trde_prica_upper"),
    ("ka10027", {"mrkt_tp": "000", "sort_tp": "1", "trde_qty_cnd": "0050", "stk_cnd": "4",
                 "crd_cnd": "0", "updown_incls": "0", "pric_cnd": "0", "trde_prica_cnd": "30",
                 "stex_tp": "1"}, "pred_pre_flu_rt_upper"),
    ("ka10016", {"mrkt_tp": "000", "ntl_tp": "1", "high_low_close_tp": "1", "stk_cnd": "1",
                 "trde_qty_tp": "00050", "crd_cnd": "0", "updown_incls": "0", "dt": "60",
                 "stex_tp": "1"}, "ntl_pric"),
]

MIN_AVG_TRADING_VALUE = 1_000_000_000  # 위생 필터 기본 하한 10억 (setting으로 조정)


class Collector:
    def __init__(
        self,
        client: KiwoomClient,
        session_factory,
        settings: Settings,
        condition_source=None,  # async (seq:str) -> list[code] — RealtimeGateway 조건검색 (FR-13)
    ):
        self._client = client
        self._sf = session_factory
        self._settings = settings
        self._condition_source = condition_source

    # ── 후보 수집 (깔때기 1단계) ──────────────────────────────────

    async def collect_candidates(self) -> dict[str, dict]:
        """랭킹 TR + 조건검색 후보 합집합 (중복 제거). {code: {name, flu_rt, trde_prica}}"""
        found: dict[str, dict] = {}

        def add(code: str, name: str = "", **extra):
            code = (code or "").strip()
            if not code:
                return
            entry = found.setdefault(code, {"name": name})
            if name:
                entry["name"] = name
            for k, v in extra.items():
                if v is not None:
                    entry[k] = v

        for tr_id, body, list_key in RANKING_CALLS:
            try:
                rows = await self._client.call_all(tr_id, body, list_key, max_pages=2)
            except Exception as e:  # 랭킹 1종 실패가 전체 스캔을 막지 않게
                log.warning("랭킹 %s 실패: %s", tr_id, e)
                continue
            for r in rows:
                add(r.get("stk_cd", ""), r.get("stk_nm", ""),
                    flu_rt=pnum(r.get("flu_rt")) if "flu_rt" in r else None,
                    trde_prica=pnum(r.get("trde_prica")) * 1_000_000 if "trde_prica" in r else None)

        # 외국인/기관 순매수 상위 (ka90009)
        try:
            data, _ = await self._client.call(
                "ka90009",
                {"mrkt_tp": "000", "amt_qty_tp": "1", "qry_dt_tp": "0", "date": "", "stex_tp": "1"},
            )
            for r in data.get("frgnr_orgn_trde_upper") or []:
                add(r.get("for_netprps_stk_cd", ""), r.get("for_netprps_stk_nm", ""))
                add(r.get("orgn_netprps_stk_cd", ""), r.get("orgn_netprps_stk_nm", ""))
        except Exception as e:
            log.warning("ka90009 실패: %s", e)

        # 전략 매핑된 조건검색식 (FR-13, D-07)
        if self._condition_source is not None:
            with self._sf() as s:
                conds = s.scalars(
                    select(ConditionMap).where(ConditionMap.enabled, ConditionMap.profile != "")
                ).all()
            for cond in conds:
                try:
                    for code in await self._condition_source(cond.seq):
                        add(code)
                except Exception as e:
                    log.warning("조건검색 %s(%s) 실패: %s", cond.name, cond.seq, e)

        log.info("후보 수집: %d종목", len(found))
        return found

    # ── 위생 필터 (FR-12) ─────────────────────────────────────────

    def hygiene_filter(self, codes: list[str]) -> tuple[list[str], list[str]]:
        """(통과, 탈락). 관리·정지·위험/경고·저유동성 제외."""
        from ..db import get_setting_float

        kept, dropped = [], []
        with self._sf() as s:
            min_tv = get_setting_float(s, "hygiene.min_avg_trading_value", MIN_AVG_TRADING_VALUE)
            for code in codes:
                inst = s.get(Instrument, code)
                if inst is not None:
                    if inst.is_managed or inst.is_halted or inst.is_warned:
                        dropped.append(code)
                        continue
                    if 0 < inst.avg_trading_value < min_tv:
                        dropped.append(code)
                        continue
                kept.append(code)
        return kept, dropped

    # ── 시세 적재 (NFR-06) ────────────────────────────────────────

    async def ingest_daily(self, code: str) -> None:
        """일봉 증분 적재: DB의 최신 일자 이후만 저장."""
        with self._sf() as s:
            latest: date | None = s.scalar(
                select(func.max(DailyPrice.date)).where(DailyPrice.code == code)
            )
        data, _ = await self._client.call(
            "ka10081",
            {"stk_cd": code, "base_dt": datetime.now().strftime("%Y%m%d"), "upd_stkpc_tp": "1"},
        )
        rows = data.get("stk_dt_pole_chart_qry") or []
        new_rows = []
        for r in rows:
            dt = datetime.strptime(r["dt"], "%Y%m%d").date()
            if latest is not None and dt <= latest:
                continue
            new_rows.append(
                DailyPrice(
                    code=code, date=dt,
                    open=price(r.get("open_pric")), high=price(r.get("high_pric")),
                    low=price(r.get("low_pric")), close=price(r.get("cur_prc")),
                    volume=int(pnum(r.get("trde_qty"))),
                    trading_value=pnum(r.get("trde_prica")) * 1_000_000,  # 백만원 → 원
                )
            )
        if new_rows:
            with self._sf() as s:
                s.add_all(new_rows)
                # 20일 평균 거래대금 갱신 → 위생 필터 근거
                closes = s.scalars(
                    select(DailyPrice).where(DailyPrice.code == code)
                    .order_by(DailyPrice.date.desc()).limit(20)
                ).all()
                avg_tv = sum(p.trading_value for p in closes) / len(closes) if closes else 0.0
                inst = s.get(Instrument, code)
                if inst is None:
                    inst = Instrument(code=code)
                    s.add(inst)
                inst.avg_trading_value = avg_tv
                s.commit()

    def load_series(self, code: str, limit: int = 250) -> tuple[list[float], list[float], float]:
        """(closes, volumes, 최근 거래대금) — 과거→최신."""
        with self._sf() as s:
            rows = s.scalars(
                select(DailyPrice).where(DailyPrice.code == code)
                .order_by(DailyPrice.date.desc()).limit(limit)
            ).all()
        rows.reverse()
        closes = [r.close for r in rows]
        volumes = [float(r.volume) for r in rows]
        tv = rows[-1].trading_value if rows else 0.0
        return closes, volumes, tv

    # ── 수급 (ka10131 — 시장별 1회 조회로 전 종목 매핑) ───────────

    async def fetch_supply_map(self) -> dict[str, tuple[int, int]]:
        """{code: (외국인 연속순매수일, 기관 연속순매수일)}"""
        supply: dict[str, tuple[int, int]] = {}
        for mrkt in ("001", "101"):
            try:
                rows = await self._client.call_all(
                    "ka10131",
                    {"dt": "5", "strt_dt": "", "end_dt": "", "mrkt_tp": mrkt,
                     "netslmt_tp": "2", "stk_inds_tp": "0", "amt_qty_tp": "0", "stex_tp": "1"},
                    "orgn_frgnr_cont_trde_prst", max_pages=2,
                )
            except Exception as e:
                log.warning("ka10131(%s) 실패: %s", mrkt, e)
                continue
            for r in rows:
                code = (r.get("stk_cd") or "").strip()
                if code:
                    supply[code] = (
                        int(pnum(r.get("frgnr_cont_netprps_dys"))),
                        int(pnum(r.get("orgn_cont_netprps_dys"))),
                    )
        return supply

    # ── 상세 (깔때기 2단계) ───────────────────────────────────────

    async def build_candidate(
        self, code: str, meta: dict, supply_map: dict[str, tuple[int, int]]
    ) -> Candidate:
        data, _ = await self._client.call("ka10001", {"stk_cd": code})
        await self.ingest_daily(code)
        closes, volumes, tv = self.load_series(code)
        f_days, i_days = supply_map.get(code, (0, 0))
        with self._sf() as s:
            inst = s.get(Instrument, code)
            if inst is not None and not inst.name and data.get("stk_nm"):
                inst.name = data["stk_nm"]
                s.commit()
        return Candidate(
            code=code,
            name=data.get("stk_nm") or meta.get("name", ""),
            closes=closes,
            volumes=volumes,
            trading_value=meta.get("trde_prica") or tv,
            per=pnum(data.get("per"), None) if data.get("per") else None,
            pbr=pnum(data.get("pbr"), None) if data.get("pbr") else None,
            roe=pnum(data.get("roe"), None) if data.get("roe") else None,
            credit_ratio=pnum(data.get("crd_rt"), None) if data.get("crd_rt") else None,
            foreign_net=[1.0] * f_days,
            inst_net=[1.0] * i_days,
            change_rate=meta.get("flu_rt", 0.0) or 0.0,
        )

    async def scan(self) -> list[Candidate]:
        """깔때기 전체: 후보 수집 → 위생 필터 → 상세 조회 (설계 §5.1 1~4단계)."""
        found = await self.collect_candidates()
        kept, dropped = self.hygiene_filter(list(found))
        if dropped:
            log.info("위생 필터 탈락 %d종목: %s", len(dropped), dropped[:10])
        candidates = []
        supply_map = await self.fetch_supply_map()
        for code in kept:
            try:
                candidates.append(await self.build_candidate(code, found[code], supply_map))
            except Exception as e:
                log.warning("상세 조회 실패 %s: %s", code, e)
        return candidates

    # ── 시장 국면 (FR-14) ─────────────────────────────────────────

    async def update_regime(self) -> tuple[str, dict]:
        closes: dict[str, list[float]] = {}
        for inds in ("001", "101"):  # KOSPI, KOSDAQ
            data, _ = await self._client.call(
                "ka20006", {"inds_cd": inds, "base_dt": datetime.now().strftime("%Y%m%d")}
            )
            rows = data.get("inds_dt_pole_qry") or []
            series = [price(r.get("cur_prc")) for r in reversed(rows)]
            closes[inds] = series
        label, metrics = classify_regime(closes.get("001", []), closes.get("101", []))
        today = date.today()
        with self._sf() as s:
            row = s.get(MarketRegime, today)
            if row:
                row.label, row.metrics = label, metrics
            else:
                s.add(MarketRegime(date=today, label=label, metrics=metrics))
            s.commit()
        return label, metrics
