from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _preview(text: str | None, limit: int = 240) -> str:
    value = (text or "").strip()
    return value[:limit] + "..." if len(value) > limit else value


async def create_history(container, thread_id: str, original_code: str) -> None:
    """Write a minimal history record when a new review starts."""
    await container.upsert_item({
        "id": thread_id,
        "thread_id": thread_id,
        "status": "running",
        "code_preview": _preview(original_code),
        "updated_at": _now(),
    })


async def update_history(container, thread_id: str, status: str) -> None:
    """Update status on the existing history record."""
    try:
        doc = await container.read_item(item=thread_id, partition_key=thread_id)
    except Exception:
        return
    doc["status"] = status
    doc["updated_at"] = _now()
    await container.upsert_item(doc)


async def list_history(container, limit: int = 30) -> list[dict]:
    docs: list[dict] = []
    async for doc in container.query_items(
        query="SELECT * FROM c ORDER BY c.updated_at DESC",
    ):
        docs.append(doc)
        if len(docs) >= limit:
            break
    return docs
