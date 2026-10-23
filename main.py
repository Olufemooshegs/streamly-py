import json
import uuid
import asyncio
from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from typing import Optional

# UPDATED IMPORTS: Added prune_old_runs and run_exists
from db import (
    init_db, create_run, get_run_by_idempotency_key, get_events_after, 
    get_expired_runs, get_completed_stages, prune_old_runs, run_exists
)
from manager import manager

# --- BACKGROUND WORKERS ---

async def recovery_worker():
    """Scans for expired runs and resumes them."""
    while True:
        await asyncio.sleep(5) 
        try:
            expired_runs = await get_expired_runs()
            for run in expired_runs:
                run_id = run["id"]
                topic = run["topic"]
                print(f"⚠️ RECOVERY WORKER: Found expired run {run_id}. Resuming...")
                
                completed = await get_completed_stages(run_id)
                manager.start_run(run_id, topic, completed_stages=completed)
        except Exception as e:
            print(f"Recovery worker error: {e}")

async def retention_worker():
    """CHALLENGE 6: Deletes runs older than 2 minutes. Runs every 30 seconds."""
    while True:
        await asyncio.sleep(30)
        try:
            await prune_old_runs(minutes_old=2) 
        except Exception as e:
            print(f"Retention worker error: {e}")

# --- LIFESPAN & APP SETUP ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # Start both workers
    recovery_task = asyncio.create_task(recovery_worker())
    retention_task = asyncio.create_task(retention_worker()) 
    yield
    # Clean up on shutdown
    recovery_task.cancel()
    retention_task.cancel()

app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def serve_index():
    return FileResponse("static/index.html")

# --- API ENDPOINTS ---

@app.post("/api/runs")
async def create_run_endpoint(request: Request, idempotency_key: Optional[str] = Header(None)):
    body = await request.json()
    topic = body.get("topic", "")

    if idempotency_key:
        existing_run = await get_run_by_idempotency_key(idempotency_key)
        if existing_run:
            return {"runId": existing_run["id"], "status": existing_run["status"]}

    run_id = str(uuid.uuid4())
    await create_run(run_id, topic, idempotency_key)
    manager.start_run(run_id, topic)
    
    return {"runId": run_id, "status": "running"}

@app.post("/api/runs/{run_id}/cancel")
async def cancel_run_endpoint(run_id: str):
    await manager.cancel_run(run_id)
    return {"status": "cancelling"}

# CHALLENGE 6: Status endpoint for the frontend to check if a run was pruned
@app.get("/api/runs/{run_id}/status")
async def get_run_status(run_id: str):
    exists = await run_exists(run_id)
    if not exists:
        raise HTTPException(status_code=410, detail="Run expired or deleted")
    return {"status": "exists"}

@app.get("/api/runs/{run_id}/events")
async def stream_events(run_id: str, request: Request, after: int = 0, last_event_id: Optional[str] = Header(None)):
    cursor = after
    if last_event_id and ":" in last_event_id:
        try:
            cursor = max(cursor, int(last_event_id.split(":")[1]))
        except ValueError:
            pass

    history = await get_events_after(run_id, cursor)
    q = manager.register_stream(run_id)

    async def event_generator():
        try:
            for ev in history:
                yield f"id: {ev['event_id']}\nevent: replay\ndata: {json.dumps(ev)}\n\n"
            
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=1.0)
                    yield f"id: {ev['event_id']}\ndata: {json.dumps(ev)}\n\n"
                    if ev['type'] in ["run.completed", "run.failed", "run.cancelled"]:
                        break
                except asyncio.TimeoutError:
                    continue
        finally:
            manager.unregister_stream(run_id, q)

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
        "Content-Encoding": "identity"
    }
    
    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=headers)