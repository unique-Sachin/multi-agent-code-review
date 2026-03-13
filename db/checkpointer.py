import base64
from typing import Any, AsyncIterator, Iterator, Optional, Sequence

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    get_checkpoint_id,
)


class AsyncCosmosDBSaver(BaseCheckpointSaver):

    def __init__(self, checkpoints_container, writes_container):
        super().__init__()
        self._cp = checkpoints_container
        self._wr = writes_container

    # ── Document ID helpers ───────────────────────────────────────────────────
    # Cosmos DB document ids cannot contain '/', so we use '|' as separator.

    @staticmethod
    def _cp_id(thread_id: str, ns: str, checkpoint_id: str) -> str:
        return f"{thread_id}|{ns}|{checkpoint_id}"

    @staticmethod
    def _wr_id(thread_id: str, ns: str, checkpoint_id: str, task_id: str, idx: int) -> str:
        return f"{thread_id}|{ns}|{checkpoint_id}|{task_id}|{idx}"

    # ── Serialization ─────────────────────────────────────────────────────────

    def _enc(self, obj: Any) -> tuple[str, str]:
        """Serialize to (type_tag, base64_string) safe for Cosmos DB JSON."""
        t, data = self.serde.dumps_typed(obj)
        if isinstance(data, str):
            data = data.encode("utf-8")
        return t, base64.b64encode(data).decode("ascii")

    def _dec(self, t: str, data: str) -> Any:
        """Deserialize from (type_tag, base64_string)."""
        return self.serde.loads_typed((t, base64.b64decode(data)))

    # ── Async interface (used by LangGraph in FastAPI async context) ──────────

    async def aget_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        thread_id = config["configurable"]["thread_id"]
        ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = get_checkpoint_id(config)

        if checkpoint_id:
            try:
                item = await self._cp.read_item(
                    item=self._cp_id(thread_id, ns, checkpoint_id),
                    partition_key=thread_id,
                )
            except Exception:
                return None
        else:
            # Fetch the latest checkpoint ordered by Cosmos system timestamp
            rows = [
                r async for r in self._cp.query_items(
                    query=(
                        "SELECT * FROM c "
                        "WHERE c.thread_id=@tid AND c.checkpoint_ns=@ns "
                        "ORDER BY c._ts DESC OFFSET 0 LIMIT 1"
                    ),
                    parameters=[
                        {"name": "@tid", "value": thread_id},
                        {"name": "@ns", "value": ns},
                    ],
                    partition_key=thread_id,
                )
            ]
            if not rows:
                return None
            item = rows[0]

        # Fetch pending writes for this checkpoint
        pending_writes = [
            (w["task_id"], w["channel"], self._dec(w["val_type"], w["val"]))
            async for w in self._wr.query_items(
                query=(
                    "SELECT * FROM c "
                    "WHERE c.thread_id=@tid AND c.checkpoint_ns=@ns "
                    "AND c.checkpoint_id=@cid"
                ),
                parameters=[
                    {"name": "@tid", "value": thread_id},
                    {"name": "@ns", "value": ns},
                    {"name": "@cid", "value": item["checkpoint_id"]},
                ],
                partition_key=thread_id,
            )
        ]

        parent_config = (
            {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": ns,
                    "checkpoint_id": item["parent_checkpoint_id"],
                }
            }
            if item.get("parent_checkpoint_id")
            else None
        )

        return CheckpointTuple(
            config={
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": ns,
                    "checkpoint_id": item["checkpoint_id"],
                }
            },
            checkpoint=self._dec(item["cp_type"], item["cp"]),
            metadata=self._dec(item["meta_type"], item["meta"]),
            parent_config=parent_config,
            pending_writes=pending_writes,
        )

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: dict,
    ) -> RunnableConfig:
        thread_id = config["configurable"]["thread_id"]
        ns = config["configurable"].get("checkpoint_ns", "")
        parent_id = get_checkpoint_id(config)
        checkpoint_id = checkpoint["id"]

        cp_type, cp_data = self._enc(checkpoint)
        meta_type, meta_data = self._enc(metadata)

        await self._cp.upsert_item({
            "id": self._cp_id(thread_id, ns, checkpoint_id),
            "thread_id": thread_id,
            "checkpoint_ns": ns,
            "checkpoint_id": checkpoint_id,
            "parent_checkpoint_id": parent_id,
            "cp_type": cp_type,
            "cp": cp_data,
            "meta_type": meta_type,
            "meta": meta_data,
        })

        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": ns,
                "checkpoint_id": checkpoint_id,
            }
        }

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
    ) -> None:
        thread_id = config["configurable"]["thread_id"]
        ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = config["configurable"]["checkpoint_id"]

        for idx, (channel, value) in enumerate(writes):
            val_type, val_data = self._enc(value)
            await self._wr.upsert_item({
                "id": self._wr_id(thread_id, ns, checkpoint_id, task_id, idx),
                "thread_id": thread_id,
                "checkpoint_ns": ns,
                "checkpoint_id": checkpoint_id,
                "task_id": task_id,
                "channel": channel,
                "val_type": val_type,
                "val": val_data,
            })

    async def alist(
        self,
        config: Optional[RunnableConfig],
        *,
        filter: Optional[dict] = None,
        before: Optional[RunnableConfig] = None,
        limit: Optional[int] = None,
    ) -> AsyncIterator[CheckpointTuple]:
        thread_id = config["configurable"]["thread_id"]
        ns = config["configurable"].get("checkpoint_ns", "")
        async for item in self._cp.query_items(
            query=(
                "SELECT * FROM c "
                "WHERE c.thread_id=@tid AND c.checkpoint_ns=@ns "
                "ORDER BY c._ts DESC"
            ),
            parameters=[
                {"name": "@tid", "value": thread_id},
                {"name": "@ns", "value": ns},
            ],
            partition_key=thread_id,
        ):
            parent_config = (
                {
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": ns,
                        "checkpoint_id": item["parent_checkpoint_id"],
                    }
                }
                if item.get("parent_checkpoint_id")
                else None
            )
            yield CheckpointTuple(
                config={
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": ns,
                        "checkpoint_id": item["checkpoint_id"],
                    }
                },
                checkpoint=self._dec(item["cp_type"], item["cp"]),
                metadata=self._dec(item["meta_type"], item["meta"]),
                parent_config=parent_config,
                pending_writes=[],
            )

    # ── Sync stubs (required by ABC, not used in async FastAPI context) ───────

    def get_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        raise NotImplementedError("Use aget_tuple")

    def put(self, config, checkpoint, metadata, new_versions) -> RunnableConfig:
        raise NotImplementedError("Use aput")

    def put_writes(self, config, writes, task_id) -> None:
        raise NotImplementedError("Use aput_writes")

    def list(self, config, **kwargs) -> Iterator[CheckpointTuple]:
        raise NotImplementedError("Use alist")
