"""FastAPI 앱 조립 (설계 §2 API Layer, §4.2)."""

import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from ..config import Settings, load_settings
from ..db import init_db
from ..kiwoom import KiwoomClient
from ..logsetup import register_secret, setup_logging
from .routes import router

log = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    client: KiwoomClient | None = None,
    with_scheduler: bool = True,
) -> FastAPI:
    settings = settings or load_settings()
    setup_logging()
    register_secret(settings.kiwoom_appkey)
    register_secret(settings.kiwoom_secretkey)
    register_secret(settings.account_no)
    init_db(settings.db_path)

    import herongs.db as dbmod
    from ..services.collector import Collector
    from ..services.notifier import Notifier
    from ..services.orders import OrderService
    from ..services.realtime import RealtimeGateway
    from ..services.recommendation import RecommendationService

    client = client or KiwoomClient(settings)
    sf = dbmod.SessionLocal
    notifier = Notifier(settings, sf)
    realtime = RealtimeGateway(client, settings, sf)
    collector = Collector(client, sf, settings, condition_source=realtime.run_condition)
    orders = OrderService(client, sf, settings)
    recommendations = RecommendationService(collector, sf, settings, notify=notifier.send_event)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        scheduler = None
        if with_scheduler:
            from ..services.scheduler import build_scheduler

            scheduler = build_scheduler(app.state)
            scheduler.start()
            await notifier.send_text("HERONGS 백엔드 기동 (§11.5 heartbeat)")
        yield
        if scheduler:
            scheduler.shutdown(wait=False)
            await notifier.send_text("HERONGS 백엔드 정상 종료")
        await client.aclose()

    app = FastAPI(title="HERONGS", lifespan=lifespan)
    st = app.state
    st.settings = settings
    st.sf = sf
    st.client = client
    st.notifier = notifier
    st.realtime = realtime
    st.collector = collector
    st.orders = orders
    st.recommendations = recommendations
    st.sessions = {}  # PIN 세션 토큰 (§7)

    app.include_router(router, prefix="/api")

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    # PWA 정적 서빙 (D-04): 빌드 산출물이 있으면 루트에 마운트
    static_dir = Path(__file__).resolve().parents[2] / "static"
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="pwa")

    return app


def new_session_token() -> str:
    return secrets.token_urlsafe(32)
