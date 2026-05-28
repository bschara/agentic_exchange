import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from api.websocket_hub import ConnectionManager
from api.routes_ws import router as ws_router, init_routes
from api.routes_http import router as http_router, init_http_routes
from api.routes_user_agents import router as user_agents_router, init_user_agent_routes
from agents.orchestrator import AgentOrchestrator

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

hub = ConnectionManager()
orchestrator = AgentOrchestrator(hub)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_routes(hub, orchestrator)
    init_http_routes(hub, orchestrator, orchestrator._state_bus)
    init_user_agent_routes(hub, orchestrator)
    await orchestrator.start_all()
    yield
    await orchestrator.stop_all()


app = FastAPI(title="Agentic Exchange", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ws_router)
app.include_router(http_router)
app.include_router(user_agents_router, prefix="/user")
