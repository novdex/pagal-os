"""PAGAL OS API Routes -- modular route package.

Combines all sub-routers into a single ``router`` that the server includes.
Each sub-module creates its own APIRouter with the appropriate prefix.
"""

from fastapi import APIRouter

from src.api.routes.agents import router as agents_router
from src.api.routes.automation import router as automation_router
from src.api.routes.hands import router as hands_router
from src.api.routes.memory_routes import router as memory_routes_router
from src.api.routes.pages import router as pages_router
from src.api.routes.store import router as store_router
from src.api.routes.system import router as system_router
from src.api.routes.teams import router as teams_router
from src.api.routes.tools import router as tools_router

router = APIRouter()

router.include_router(agents_router)
router.include_router(hands_router)
router.include_router(teams_router)
router.include_router(store_router)
router.include_router(system_router)
router.include_router(memory_routes_router)
router.include_router(automation_router)
router.include_router(tools_router)
router.include_router(pages_router)
