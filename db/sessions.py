"""
Cosmos DB helpers for the sessions container.

Stale-running detection: if a session has been 'running' for more than
STALE_TIMEOUT_SECONDS (default 300 s / 5 min), get_session() promotes it
to 'error' automatically. This handles the server-restart scenario where the
background task was killed but the DB record was never cleaned up.
"""

from datetime import datetime, timezone, timedelta

STALE_TIMEOUT_SECONDS = 300  # 5 minutes


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def upsert_session(
    container,
    thread_id: str,
    stage: str,
    error_msg: str | None = None,
) -> None:
    await container.upsert_item({
        "id": thread_id,
        "thread_id": thread_id,
        "stage": stage,
        "error_msg": error_msg,
        "updated_at": _now(),
    })


async def delete_session(container, thread_id: str) -> None:
    """Remove the session record (called on successful pipeline completion)."""
    try:
        await container.delete_item(item=thread_id, partition_key=thread_id)
    except Exception:
        pass  # already absent is fine


async def get_session(container, thread_id: str) -> dict | None:
    """
    Return the session document, or None if not found.
    """
    try:
        doc = await container.read_item(item=thread_id, partition_key=thread_id)
    except Exception:
        return None

    if doc.get("stage") == "running":
        updated_at_str = doc.get("updated_at")
        if updated_at_str:
            updated_at = datetime.fromisoformat(updated_at_str)
            if (datetime.now(timezone.utc) - updated_at) > timedelta(seconds=STALE_TIMEOUT_SECONDS):
                doc["stage"] = "error"
                doc["error_msg"] = "Pipeline timed out or the server was restarted while it was running."
                doc["updated_at"] = _now()
                await container.upsert_item(doc)

    return doc
