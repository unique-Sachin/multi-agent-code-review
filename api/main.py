from dotenv import load_dotenv
load_dotenv()

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers.review import router as review_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup: initialise Azure Cosmos DB, build the LangGraph compiled app with
    the Cosmos DB checkpointer, and inject both into the review service.
    Shutdown: close the Cosmos DB client cleanly.
    """
    from azure.cosmos.aio import CosmosClient
    from db.cosmos import COSMOS_ENDPOINT, COSMOS_KEY, init_containers
    from db.checkpointer import AsyncCosmosDBSaver
    from graph import build_graph
    from api.services import review as review_service

    client = CosmosClient(url=COSMOS_ENDPOINT, credential=COSMOS_KEY)
    try:
        cp_container, wr_container, sessions_container, history_container = await init_containers(client)
        checkpointer = AsyncCosmosDBSaver(cp_container, wr_container)
        graph = build_graph(checkpointer=checkpointer)
        review_service.init(graph, sessions_container, history_container)
        yield
    finally:
        await client.close()


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
