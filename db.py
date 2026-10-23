# db.py
import aiosqlite
import json
import uuid
from datetime import datetime, timezone, timedelta

DB_PATH = "streamly.db"

def utc_now():
    return datetime.now(timezone.utc).isoformat()

def utc_in_seconds(seconds: int):
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute("PRAGMA synchronous=NORMAL;")
        
        # Runs table (with lease for Challenge 5)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                topic TEXT NOT NULL,
                status TEXT NOT NULL,
                idempotency_key TEXT UNIQUE,
                created_at TEXT,
                updated_at TEXT,
                last_sequence INTEGER DEFAULT 0,
                error TEXT,
                cancel_requested INTEGER DEFAULT 0,
                lease_expires_at TEXT
            )
        """)
        
        # Events table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS events (
                run_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                event_id TEXT NOT NULL UNIQUE,
                type TEXT NOT NULL,
                data TEXT NOT NULL,
                created_at TEXT,
                PRIMARY KEY (run_id, sequence),
                FOREIGN KEY(run_id) REFERENCES runs(id)
            )
        """)
        
        # Notes table (for Challenge 4)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                content TEXT NOT NULL,
                idempotency_key TEXT UNIQUE,
                created_at TEXT
            )
        """)
        await db.commit()

async def get_run_by_idempotency_key(key: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM runs WHERE idempotency_key = ?", (key,)) as cursor:
            return await cursor.fetchone()

async def create_run(run_id: str, topic: str, idempotency_key: str = None):
    now = utc_now()
    lease = utc_in_seconds(15) # 15 second lease
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO runs (id, topic, status, idempotency_key, created_at, updated_at, lease_expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, topic, "running", idempotency_key, now, now, lease)
        )
        await db.commit()

async def update_run_status(run_id: str, status: str, error: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE runs SET status = ?, error = ?, updated_at = ? WHERE id = ?",
            (status, error, utc_now(), run_id)
        )
        await db.commit()

async def request_cancel(run_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE runs SET cancel_requested = 1 WHERE id = ?", (run_id,))
        await db.commit()

async def append_event(run_id: str, event_type: str, data: dict) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT last_sequence FROM runs WHERE id = ?", (run_id,)) as cursor:
            row = await cursor.fetchone()
            if not row: return None
            next_seq = row['last_sequence'] + 1

        event_id = f"{run_id}:{next_seq}"
        now = utc_now()
        
        await db.execute(
            "INSERT INTO events (run_id, sequence, event_id, type, data, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, next_seq, event_id, event_type, json.dumps(data), now)
        )
        await db.execute("UPDATE runs SET last_sequence = ?, updated_at = ? WHERE id = ?", (next_seq, now, run_id))
        await db.commit()

        return {
            "sequence": next_seq,
            "event_id": event_id,
            "type": event_type,
            "data": data,
            "created_at": now
        }

async def get_events_after(run_id: str, after_seq: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM events WHERE run_id = ? AND sequence > ? ORDER BY sequence ASC",
            (run_id, after_seq)
        ) as cursor:
            rows = await cursor.fetchall()
            return [{
                "sequence": r["sequence"],
                "event_id": r["event_id"],
                "type": r["type"],
                "data": json.loads(r["data"]),
                "created_at": r["created_at"]
            } for r in rows]

async def add_note_idempotently(run_id: str, content: str, idempotency_key: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO notes (id, run_id, content, idempotency_key, created_at) VALUES (?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), run_id, content, idempotency_key, utc_now())
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

# --- CHALLENGE 5: LEASE & RECOVERY FUNCTIONS ---
async def renew_lease(run_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE runs SET lease_expires_at = ? WHERE id = ?",
            (utc_in_seconds(15), run_id)
        )
        await db.commit()

async def get_expired_runs():
    now = utc_now()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, topic FROM runs WHERE status = 'running' AND lease_expires_at < ?", 
            (now,)
        ) as cursor:
            return await cursor.fetchall()

async def get_completed_stages(run_id: str) -> list[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT data FROM events WHERE run_id = ? AND type = 'checkpoint'", (run_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [json.loads(r["data"])["stage"] for r in rows]

# --- CHALLENGE 6: RETENTION POLICY FUNCTIONS ---
async def prune_old_runs(minutes_old: int):
    """Deletes runs older than X minutes."""
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes_old)).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
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