"""내부 REST API (설계 §4.2) + PIN 세션 인증 (§7)."""

import secrets
import time
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select

from ..models import (
    ConditionMap,
    Instrument,
    MarketRegime,
    Opinion,
    Recommendation,
    Setting,
    Watchlist,
)
from ..services.orders import GuardrailError

router = APIRouter()

SESSION_COOKIE = "herongs_session"
SESSION_TTL = 12 * 3600

# 로그인 무차별 대입 방어 (DCR-001): 연속 실패 5회 → 300초 전역 잠금
LOCKOUT_AFTER = 5
LOCKOUT_SECONDS = 300

# 인증 없이 허용되는 경로 (로그인 자체)
_PUBLIC = {"/api/auth/login"}


def _auth(request: Request) -> None:
    """PIN 세션 확인. settings.pin이 비어 있으면 인증 비활성(로컬 개발)."""
    st = request.app.state
    if not st.settings.pin:
        return
    if request.url.path in _PUBLIC:
        return
    token = request.cookies.get(SESSION_COOKIE)
    exp = st.sessions.get(token)
    if not token or exp is None or exp < time.time():
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")


class LoginBody(BaseModel):
    pin: str


@router.post("/auth/login")
def login(body: LoginBody, request: Request, response: Response):
    st = request.app.state
    if not st.settings.pin:
        return {"ok": True, "auth": "disabled"}
    la = st.login_attempts
    now = time.time()
    if now < la["locked_until"]:
        raise HTTPException(
            status_code=429,
            detail=f"로그인이 잠겼습니다. {int(la['locked_until'] - now) + 1}초 후 다시 시도하세요",
        )
    if not secrets.compare_digest(body.pin.encode(), st.settings.pin.encode()):
        la["fails"] += 1
        if la["fails"] >= LOCKOUT_AFTER:
            la["fails"] = 0
            la["locked_until"] = now + LOCKOUT_SECONDS
        raise HTTPException(status_code=401, detail="PIN이 올바르지 않습니다")
    la["fails"] = 0
    from .app import new_session_token

    token = new_session_token()
    st.sessions[token] = time.time() + SESSION_TTL
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="strict",
                        max_age=SESSION_TTL)
    return {"ok": True}


# ── 추천 (FR-04/05) ──────────────────────────────────────────────


@router.get("/recommendations")
def recommendations(request: Request, profile: str = "swing"):
    _auth(request)
    st = request.app.state
    with st.sf() as s:
        latest_ts = s.scalar(
            select(Recommendation.ts)
            .where(Recommendation.profile == profile)
            .order_by(Recommendation.ts.desc()).limit(1)
        )
        if latest_ts is None:
            return {"profile": profile, "ts": None, "items": []}
        rows = s.scalars(
            select(Recommendation)
            .where(Recommendation.profile == profile, Recommendation.ts == latest_ts)
            .order_by(Recommendation.rank)
        ).all()
        names = {
            i.code: i.name
            for i in s.scalars(
                select(Instrument).where(Instrument.code.in_([r.code for r in rows]))
            ).all()
        }
    return {
        "profile": profile,
        "ts": latest_ts.isoformat(),
        "items": [
            {"rank": r.rank, "code": r.code, "name": names.get(r.code, ""),
             "score": r.score, "breakdown": r.score_breakdown, "regime": r.regime}
            for r in rows
        ],
    }


@router.post("/scan")
async def run_scan(request: Request):
    """수동 스캔 트리거 (AC-02)."""
    _auth(request)
    st = request.app.state
    await st.collector.update_regime()
    return await st.recommendations.run_scan()


# ── 개별 종목 분석 (FR-06/07) ────────────────────────────────────


@router.get("/stocks/{code}/analysis")
async def stock_analysis(code: str, request: Request):
    _auth(request)
    st = request.app.state
    try:
        holdings = await st.orders.holdings()
    except Exception:
        holdings = {}
    return await st.recommendations.analyze_stock(code, holdings)


@router.get("/stocks/{code}/quote")
async def stock_quote(code: str, request: Request, with_account: bool = True):
    """주문 보조 정보 — 시세·호가(+계좌) (FR-20/21/22, AC-13/14)."""
    _auth(request)
    return await request.app.state.orders.quote(code, with_account)


@router.get("/stocks/{code}/prices")
def stock_prices(code: str, request: Request, limit: int = 120):
    """차트용 일봉 (FR-06). 적재분(daily_price)에서 반환."""
    _auth(request)
    from ..models import DailyPrice

    with request.app.state.sf() as s:
        rows = s.scalars(
            select(DailyPrice).where(DailyPrice.code == code)
            .order_by(DailyPrice.date.desc()).limit(limit)
        ).all()
    rows.reverse()
    return [
        {"time": r.date.isoformat(), "open": r.open, "high": r.high,
         "low": r.low, "close": r.close, "volume": r.volume}
        for r in rows
    ]


# ── 포트폴리오 (FR-07/09) ────────────────────────────────────────


@router.get("/portfolio")
async def portfolio(request: Request):
    _auth(request)
    st = request.app.state
    pf = await st.orders.portfolio()
    # 보유 종목의 최근 의견 첨부
    with st.sf() as s:
        for stock in pf["stocks"]:
            ops = s.scalars(
                select(Opinion).where(Opinion.code == stock["code"])
                .order_by(Opinion.ts.desc()).limit(3)
            ).all()
            stock["opinions"] = {o.profile: o.stance for o in ops}
    return pf


# ── 주문 (FR-08/09/15, AC-04/10) ─────────────────────────────────


class PreviewBody(BaseModel):
    side: str
    code: str
    qty: int
    price: float
    profile: str = "swing"


class ConfirmBody(BaseModel):
    preview_id: str


@router.post("/orders/preview")
async def order_preview(body: PreviewBody, request: Request):
    _auth(request)
    try:
        return await request.app.state.orders.preview(
            body.side, body.code, body.qty, body.price, body.profile
        )
    except GuardrailError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/orders/confirm")
async def order_confirm(body: ConfirmBody, request: Request):
    _auth(request)
    try:
        return await request.app.state.orders.confirm(body.preview_id)
    except GuardrailError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/orders/open")
async def open_orders(request: Request):
    _auth(request)
    return await request.app.state.orders.open_orders()


class ModifyBody(BaseModel):
    code: str
    qty: int
    price: float


@router.put("/orders/{ord_no}")
async def modify_order(ord_no: str, body: ModifyBody, request: Request):
    _auth(request)
    try:
        return await request.app.state.orders.modify(ord_no, body.code, body.qty, body.price)
    except GuardrailError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.delete("/orders/{ord_no}")
async def cancel_order(ord_no: str, code: str, request: Request, qty: int = 0):
    _auth(request)
    return await request.app.state.orders.cancel(ord_no, code, qty)


# ── 성과 (FR-16, AC-09) ──────────────────────────────────────────


@router.get("/performance")
def performance(request: Request, profile: str | None = None):
    _auth(request)
    svc = request.app.state.recommendations
    return {"report": svc.performance_report(), "history": svc.history(profile)}


# ── 국면·조건식·설정 (FR-13/14) ──────────────────────────────────


@router.get("/regime")
def regime(request: Request):
    _auth(request)
    with request.app.state.sf() as s:
        row = s.scalars(
            select(MarketRegime).order_by(MarketRegime.date.desc()).limit(1)
        ).first()
    if row is None:
        return {"label": "sideways", "date": None, "metrics": {}}
    return {"label": row.label, "date": row.date.isoformat(), "metrics": row.metrics}


@router.get("/conditions")
async def conditions(request: Request, refresh: bool = False):
    """HTS 등록 조건식 목록 + 전략 매핑 (AC-08)."""
    _auth(request)
    st = request.app.state
    if refresh:
        await st.realtime.refresh_conditions()
    with st.sf() as s:
        rows = s.scalars(select(ConditionMap)).all()
    return [
        {"seq": r.seq, "name": r.name, "profile": r.profile, "enabled": r.enabled}
        for r in rows
    ]


class ConditionBody(BaseModel):
    profile: str = ""
    enabled: bool = True


@router.put("/conditions/{seq}")
def map_condition(seq: str, body: ConditionBody, request: Request):
    _auth(request)
    with request.app.state.sf() as s:
        row = s.get(ConditionMap, seq)
        if row is None:
            raise HTTPException(status_code=404, detail="조건식이 없습니다")
        row.profile = body.profile
        row.enabled = body.enabled
        s.commit()
    return {"ok": True}


@router.get("/settings")
def get_settings(request: Request):
    _auth(request)
    st = request.app.state
    with st.sf() as s:
        rows = s.scalars(select(Setting)).all()
    return {
        "trading_mode": st.settings.trading_mode,
        "max_order_amount": st.settings.max_order_amount,
        "daily_order_limit": st.settings.daily_order_limit,
        "overrides": {r.key: r.value for r in rows},
    }


class SettingBody(BaseModel):
    key: str
    value: str


@router.put("/settings")
def put_setting(body: SettingBody, request: Request):
    _auth(request)
    from ..db import set_setting

    with request.app.state.sf() as s:
        set_setting(s, body.key, body.value)
    return {"ok": True}


# ── 관심종목 (FR-10) ─────────────────────────────────────────────


@router.get("/watchlist")
def watchlist(request: Request):
    _auth(request)
    with request.app.state.sf() as s:
        rows = s.scalars(select(Watchlist)).all()
        names = {
            i.code: i.name
            for i in s.scalars(
                select(Instrument).where(Instrument.code.in_([r.code for r in rows]))
            ).all()
        }
    return [
        {"code": r.code, "name": names.get(r.code, ""), "group": r.group_name}
        for r in rows
    ]


class WatchBody(BaseModel):
    code: str
    group: str = "default"


@router.post("/watchlist")
def add_watch(body: WatchBody, request: Request):
    _auth(request)
    with request.app.state.sf() as s:
        if s.get(Watchlist, body.code) is None:
            s.add(Watchlist(code=body.code, group_name=body.group,
                            added_at=datetime.now()))
            s.commit()
    return {"ok": True}


@router.delete("/watchlist/{code}")
def remove_watch(code: str, request: Request):
    _auth(request)
    with request.app.state.sf() as s:
        row = s.get(Watchlist, code)
        if row:
            s.delete(row)
            s.commit()
    return {"ok": True}
