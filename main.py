"""Создание приложения и подключение его API-маршрутов."""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from api.routers import router
from config.config import get_database_url
from shared.database import create_database_engine

ROOT_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Создаёт общие ресурсы БД при запуске и освобождает их при остановке."""
    database_url = get_database_url()
    engine = create_database_engine(database_url) if database_url else None
    application.state.database_engine = engine
    try:
        yield
    finally:
        if engine is not None:
            engine.dispose()


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT_DIR / "static"), name="static")
app.include_router(router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
