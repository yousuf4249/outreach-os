"""Worker process entrypoint for multi-process sending concurrency testing.

Spawned as an independent OS process to execute either a Campaign QueueSlot send
or a DirectEmail send against a shared database with mocked SMTP.
"""

import argparse
import asyncio
import json
import os
import sys
import time
from unittest.mock import patch, MagicMock

# Ensure outreach-os root is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["campaign", "direct"], required=True)
    parser.add_argument("--target-id", type=int, required=True)
    parser.add_argument("--db-url", type=str, required=True)
    parser.add_argument("--barrier-file", type=str, required=True)
    parser.add_argument("--ready-file", type=str, required=True)
    parser.add_argument("--result-file", type=str, required=True)
    args = parser.parse_args()

    os.environ["DATABASE_URL"] = args.db_url
    os.environ["TEST_DATABASE_URL"] = args.db_url

    # Late imports after environment variables are set
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from sqlalchemy import select, update
    from app.sender import SendResult
    from app.jobs import send_slot_job
    from app.routers.direct_email import execute_send_direct_email
    from app.models import DirectEmail, QueueSlot

    engine = create_async_engine(
        args.db_url,
        connect_args={"check_same_thread": False, "timeout": 30},
        echo=False,
    )
    SessionMaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Patch global engine in app.database and app.jobs so send_slot_job uses this engine
    import app.database
    import app.jobs
    app.database.engine = engine
    app.database.AsyncSessionLocal = SessionMaker
    app.jobs.AsyncSessionLocal = SessionMaker

    # Track SMTP calls
    smtp_calls = []

    def mock_send(*a, **kw):
        smtp_calls.append({"args": [str(x) for x in a], "time": time.time()})
        return SendResult(message_id=f"msg-proc-{os.getpid()}-{len(smtp_calls)}", thread_id="thr-proc-001")

    # Signal ready
    with open(args.ready_file, "w") as f:
        f.write(f"READY pid={os.getpid()}\n")

    # Wait for barrier release from parent
    while not os.path.exists(args.barrier_file):
        await asyncio.sleep(0.01)

    result_data = {
        "pid": os.getpid(),
        "mode": args.mode,
        "target_id": args.target_id,
        "smtp_sent": False,
        "error": None,
    }

    try:
        with patch("app.jobs.send_email", side_effect=mock_send), \
             patch("app.routers.direct_email.send_email", side_effect=mock_send):
            if args.mode == "campaign":
                await send_slot_job(args.target_id)
            elif args.mode == "direct":
                async with SessionMaker() as session:
                    res = await session.execute(select(DirectEmail).where(DirectEmail.id == args.target_id))
                    direct = res.scalar_one()
                    await execute_send_direct_email(session, direct)

        result_data["smtp_calls_count"] = len(smtp_calls)
        result_data["smtp_sent"] = len(smtp_calls) > 0

    except Exception as e:
        result_data["error"] = str(e)
        import traceback
        result_data["traceback"] = traceback.format_exc()

    finally:
        await engine.dispose()
        with open(args.result_file, "w") as f:
            json.dump(result_data, f)


if __name__ == "__main__":
    asyncio.run(main())
