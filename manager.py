# manager.py
import asyncio
import uuid
from db import (
    append_event, update_run_status, get_events_after, request_cancel, 
    add_note_idempotently, renew_lease
)

class RunManager:
    def __init__(self):
        self.active_streams: dict[str, list[asyncio.Queue]] = {}
        self.cancel_events: dict[str, asyncio.Event] = {}
        self.tasks: dict[str, asyncio.Task] = {}

    def register_stream(self, run_id: str) -> asyncio.Queue:
        q = asyncio.Queue()
        if run_id not in self.active_streams:
            self.active_streams[run_id] = []
        self.active_streams[run_id].append(q)
        return q

    def unregister_stream(self, run_id: str, q: asyncio.Queue):
        if run_id in self.active_streams and q in self.active_streams[run_id]:
            self.active_streams[run_id].remove(q)

    async def _publish(self, run_id: str, event: dict):
        if run_id in self.active_streams:
            for q in self.active_streams[run_id]:
                await q.put(event)

    async def cancel_run(self, run_id: str):
        await request_cancel(run_id)
        if run_id in self.cancel_events:
            self.cancel_events[run_id].set()

    # FIXED: Added completed_stages parameter
    def start_run(self, run_id: str, topic: str, completed_stages: list[str] = None):
        cancel_event = asyncio.Event()
        self.cancel_events[run_id] = cancel_event
        task = asyncio.create_task(self._execute_agent(run_id, topic, cancel_event, completed_stages))
        self.tasks[run_id] = task

    # FIXED: Accept completed_stages
    async def _execute_agent(self, run_id: str, topic: str, cancel_event: asyncio.Event, completed_stages: list[str] = None):
        stages = ["plan", "investigate", "summarize", "review"]
        if completed_stages is None:
            completed_stages = []
        
        async def heartbeat_loop():
            while True:
                await asyncio.sleep(5)
                await renew_lease(run_id) # Renew the DB lease
                event = await append_event(run_id, "heartbeat", {"ts": "ping"})
                await self._publish(run_id, event)

        hb_task = asyncio.create_task(heartbeat_loop())

        try:
            for stage in stages:
                if cancel_event.is_set(): break
                
                # Skip stages already done before the crash
                if stage in completed_stages:
                    print(f"Resuming {run_id}: Skipping completed stage '{stage}'")
                    continue
                
                event = await append_event(run_id, "stage.started", {"stage": stage})
                await self._publish(run_id, event)
                
                if stage == "investigate":
                    side_effect_key = f"{run_id}:{stage}:note"
                    note_content = f"Important finding about {topic} discovered during {stage}."
                    was_inserted = await add_note_idempotently(run_id, note_content, side_effect_key)
                    
                    if was_inserted:
                        event = await append_event(run_id, "note.added", {"content": note_content})
                    else:
                        event = await append_event(run_id, "note.skipped", {"reason": "idempotent_duplicate_prevented"})
                    await self._publish(run_id, event)

                tokens = f"Executing {stage} for topic: {topic}".split()
                for token in tokens:
                    if cancel_event.is_set(): break
                    await asyncio.sleep(0.5)
                    event = await append_event(run_id, "token", {"text": token + " "})
                    await self._publish(run_id, event)

                if cancel_event.is_set(): break

                event = await append_event(run_id, "checkpoint", {"stage": stage, "status": "committed"})
                await self._publish(run_id, event)

            if cancel_event.is_set():
                await update_run_status(run_id, "cancelled")
                event = await append_event(run_id, "run.cancelled", {"reason": "user_request"})
            else:
                await update_run_status(run_id, "completed")
                event = await append_event(run_id, "run.completed", {"message": "Research run completed."})
            
            await self._publish(run_id, event)

        except Exception as e:
            await update_run_status(run_id, "failed", str(e))
            event = await append_event(run_id, "run.failed", {"error": str(e)})
            await self._publish(run_id, event)
        finally:
            hb_task.cancel()
            if run_id in self.tasks:
                del self.tasks[run_id]

manager = RunManager()

# ... existing imports and functions ...

async def prune_old_runs(minutes_old: int):
    """Deletes runs older than X minutes (Cascade deletes events/notes)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes_old)).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        # SQLite doesn't have cascade delete by default, so delete manually
        await db.execute("DELETE FROM events WHERE run_id IN (SELECT id FROM runs WHERE updated_at < ?)", (cutoff,))
        await db.execute("DELETE FROM notes WHERE run_id IN (SELECT id FROM runs WHERE updated_at < ?)", (cutoff,))
        deleted = await db.execute("DELETE FROM runs WHERE updated_at < ?", (cutoff,))
        await db.commit()
        if deleted.rowcount > 0:
            print(f"🧹 RETENTION POLICY: Pruned {deleted.rowcount} old runs.")

async def run_exists(run_id: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM runs WHERE id = ?", (run_id,)) as cursor:
            return await cursor.fetchone() is not None