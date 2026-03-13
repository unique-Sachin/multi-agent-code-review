import os
from azure.cosmos.aio import CosmosClient
from azure.cosmos import PartitionKey
from dotenv import load_dotenv
load_dotenv()

COSMOS_ENDPOINT = os.getenv("COSMOS_ENDPOINT")
COSMOS_KEY = os.getenv("COSMOS_KEY")
COSMOS_DB_NAME = os.getenv("COSMOS_DB_NAME", "code-review-db")


async def init_containers(client: CosmosClient):
    """
    Create the Cosmos DB database and all required containers if they don't
    already exist. Returns
    (checkpoints, checkpoint_writes, sessions, review_history) proxies.

    Container layout
    ────────────────
    checkpoints       – one document per LangGraph checkpoint snapshot
    checkpoint_writes – pending channel writes between node transitions
    sessions          – tracks 'running' / 'error' background-task states
    review_history    – durable, queryable list of all sessions for UI history
    """
    db = await client.create_database_if_not_exists(
        id=COSMOS_DB_NAME,
    )

    checkpoints = await db.create_container_if_not_exists(
        id="checkpoints",
        partition_key=PartitionKey(path="/thread_id"),
    )
    writes = await db.create_container_if_not_exists(
        id="checkpoint_writes",
        partition_key=PartitionKey(path="/thread_id"),
    )
    sessions = await db.create_container_if_not_exists(
        id="sessions",
        partition_key=PartitionKey(path="/thread_id"),
    )
    review_history = await db.create_container_if_not_exists(
        id="review_history",
        partition_key=PartitionKey(path="/thread_id"),
    )

    return checkpoints, writes, sessions, review_history
