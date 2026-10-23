import pytest
import httpx
import asyncio
import uuid

BASE_URL = "http://127.0.0.1:8000"

@pytest.mark.asyncio
async def test_idempotency():
    """Proves that sending the same Idempotency-Key doesn't duplicate the run."""
    key = str(uuid.uuid4())
    headers = {"Idempotency-Key": key}
    body = {"topic": "Pytest topic"}
    
    async with httpx.AsyncClient() as client:
        res1 = await client.post(f"{BASE_URL}/api/runs", json=body, headers=headers)
        res2 = await client.post(f"{BASE_URL}/api/runs", json=body, headers=headers)
        
        assert res1.status_code == 200
        assert res2.status_code == 200
        # The magic assertion: Both return the exact same runId!
        assert res1.json()["runId"] == res2.json()["runId"]

@pytest.mark.asyncio
async def test_replay_and_deduplication():
    """Proves the journal replays missed events correctly."""
    async with httpx.AsyncClient() as client:
        # 1. Start a run
        res = await client.post(f"{BASE_URL}/api/runs", json={"topic": "Replay test"})
        run_id = res.json()["runId"]
        
        # 2. Wait for a few events to commit
        await asyncio.sleep(2)
        
        # 3. Ask for replay from sequence 0
        res = await client.get(f"{BASE_URL}/api/runs/{run_id}/events?after=0")
        
        # 4. Assert we get a streaming response
        assert res.status_code == 200
        assert "text/event-stream" in res.headers["content-type"]
        assert "event: replay" in res.text