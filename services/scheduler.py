import  asyncio
import logging

from services.broadcast_service import run_due
from services.wa_client import get_client

log = logging.getLogger("broadcast.scheduler")

async def run_broadcast_scheduler(interval: int = 30) -> None:
    client = get_client()
    log.info("Broadcast scheduler dimulai (provider=%s, interval=%ss)", type(client).__name__, interval)
    while True:
        try:
            results = await asyncio.to_thread(run_due, client, False)
            for r in results:
                log.info(
                    "Broadcast #%s: ok=%s failed=%s status=%s notes=%s",
                    r.get("id"),
                    r.get("ok"),
                    r.get("failed"),
                    r.get("status_after"),
                    r.get("notes")
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Broadcast scheduler error")
        await asyncio.sleep(interval)