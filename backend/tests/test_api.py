"""WU-09 — REST API 통합 테스트 (FastAPI TestClient)."""

import time
from pathlib import Path

from fastapi.testclient import TestClient

from herongs.api.app import create_app
from herongs.config import Settings

from .conftest import make_kiwoom_client
from .test_orders import ACCOUNT_ROUTES


def make_app(pin: str = ""):
    settings = Settings(
        kiwoom_appkey="AK", kiwoom_secretkey="SK",
        db_path=Path(":memory:"), pin=pin, _env_file=None,
    )
    client = make_kiwoom_client(ACCOUNT_ROUTES, settings)
    return create_app(settings=settings, client=client, with_scheduler=False)


def test_healthz():
    with TestClient(make_app()) as tc:
        assert tc.get("/healthz").json() == {"status": "ok"}


def test_pin_auth_required():
    with TestClient(make_app(pin="1234")) as tc:
        assert tc.get("/api/regime").status_code == 401  # 미로그인 차단 (§7)
        assert tc.post("/api/auth/login", json={"pin": "9999"}).status_code == 401
        resp = tc.post("/api/auth/login", json={"pin": "1234"})
        assert resp.status_code == 200
        assert tc.get("/api/regime").status_code == 200  # 세션 쿠키로 통과


def test_login_lockout_after_failures():
    app = make_app(pin="1234")
    with TestClient(app) as tc:
        for _ in range(5):
            assert tc.post("/api/auth/login", json={"pin": "9999"}).status_code == 401
        # 잠금 중에는 정답도 거부 (AC-SEC-01)
        assert tc.post("/api/auth/login", json={"pin": "1234"}).status_code == 429
        app.state.login_attempts["locked_until"] = time.time() - 1  # 잠금 만료 시뮬레이션
        assert tc.post("/api/auth/login", json={"pin": "1234"}).status_code == 200


def test_login_success_resets_fail_count():
    with TestClient(make_app(pin="1234")) as tc:
        for _ in range(4):
            tc.post("/api/auth/login", json={"pin": "9999"})
        assert tc.post("/api/auth/login", json={"pin": "1234"}).status_code == 200
        # 성공으로 카운터 리셋 → 이후 오답 1회는 401이지 잠금 아님 (AC-SEC-02)
        assert tc.post("/api/auth/login", json={"pin": "9999"}).status_code == 401
        assert tc.post("/api/auth/login", json={"pin": "1234"}).status_code == 200


def test_auth_disabled_when_no_pin():
    with TestClient(make_app(pin="")) as tc:
        assert tc.get("/api/regime").status_code == 200


def test_order_preview_confirm_via_api():
    with TestClient(make_app()) as tc:
        resp = tc.post("/api/orders/preview", json={
            "side": "buy", "code": "005930", "qty": 10, "price": 70000,
        })
        assert resp.status_code == 200
        pv = resp.json()
        assert pv["amount"] == 700000  # 확인 단계 정보 (FR-08/15)

        resp = tc.post("/api/orders/confirm", json={"preview_id": pv["preview_id"]})
        assert resp.status_code == 200
        assert resp.json()["ord_no"] == "0000138"  # AC-04 흐름


def test_order_guardrail_via_api():
    with TestClient(make_app()) as tc:
        resp = tc.post("/api/orders/preview", json={
            "side": "buy", "code": "005930", "qty": 1000, "price": 70000,
        })
        assert resp.status_code == 422
        assert "상한" in resp.json()["detail"]  # AC-10: 사유 표시


def test_confirm_without_preview_via_api():
    with TestClient(make_app()) as tc:
        resp = tc.post("/api/orders/confirm", json={"preview_id": "forged"})
        assert resp.status_code == 422  # AC-04: preview 우회 불가


def test_order_modify_via_api():
    with TestClient(make_app()) as tc:
        resp = tc.put("/api/orders/0000138",
                      json={"code": "005930", "qty": 5, "price": 71000})
        assert resp.status_code == 200
        assert resp.json()["ord_no"] == "0000140"  # FR-09 정정


def test_watchlist_crud():
    with TestClient(make_app()) as tc:
        assert tc.get("/api/watchlist").json() == []
        tc.post("/api/watchlist", json={"code": "005930"})
        items = tc.get("/api/watchlist").json()
        assert items[0]["code"] == "005930"
        tc.delete("/api/watchlist/005930")
        assert tc.get("/api/watchlist").json() == []


def test_portfolio_endpoint():
    with TestClient(make_app()) as tc:
        pf = tc.get("/api/portfolio").json()
        assert pf["stocks"][0]["code"] == "005930"
        assert pf["total_eval"] == 1100000.0
