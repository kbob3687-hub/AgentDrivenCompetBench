"""FastAPI应用入口 - CORS + 路由注册 + PostgreSQL生命周期"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")

# .env 必须先于这些模块导入加载（模块内会读取环境变量）
from fastapi import FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

from api.routes.analyze import router as analyze_router  # noqa: E402
from api.routes.health import router as health_router  # noqa: E402
from api.routes.survey import router as survey_router  # noqa: E402

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from storage.engine import dispose_engine, init_engine
    from storage.models import Base

    try:
        engine = await init_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("PostgreSQL connected, tables ready")
    except Exception:
        logger.warning("PostgreSQL unavailable, running without persistence")

    yield

    try:
        await dispose_engine()
    except Exception:
        pass


app = FastAPI(
    title="Competitive Analysis API",
    description="Multi-agent competitive analysis pipeline with SSE streaming",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(analyze_router)
app.include_router(survey_router)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception: %s", exc)
    return JSONResponse(status_code=500, content={"error": "服务内部错误，请重试"})
