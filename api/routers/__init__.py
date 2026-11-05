"""Route aggregation for the FastAPI application."""

from fastapi import APIRouter

from api.routers.pages import router as pages_router
from api.routers.system import router as system_router
from api.routers.site_tools import router as site_tools_router
from api.routers.vilmed import router as vilmed_router
from api.routers.xmlriver import router as xmlriver_router

router = APIRouter()
router.include_router(pages_router)
router.include_router(system_router)
router.include_router(site_tools_router)
router.include_router(vilmed_router)
router.include_router(xmlriver_router)
