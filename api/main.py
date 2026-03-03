from dotenv import load_dotenv
load_dotenv()

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers.review import router as review_router
from api.services.review import get_graph


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Warm up the LangGraph compiled app at startup so the first request isn't slow."""
    get_graph()
    yield


app = FastAPI(
    title="Multi-Agent Code Review API",
    version="1.0.0",
    description="FastAPI backend for the LangGraph multi-agent code review pipeline.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(review_router)


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}
