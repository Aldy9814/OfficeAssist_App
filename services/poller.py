import asyncio
import logging

from services.dispatcher import handle_message
from services.wa_client import GreenApiClient, get_client, parse_incoming

log = logging.getLogger("poller")
_tasks = set()

async def run_poller() -> None:
    client = get_client()
    if not isinstance(client, GreenApiClient):
        log.warning("Poller dilewati: WA_PROVIDER bukan greenapi")
        return
    log.info("Green API polling dimulai")
    while True:
        try:
            note = await asyncio.to_thread(client.receive_notification, 20)
            if not note:
                continue
            receipt_id = note["receiptId"]
            parsed = parse_incoming(note.get("body", {}))
            if parsed:
                t = asyncio.create_task(asyncio.to_thread(handle_message, parsed[0], parsed [1], client))
                _tasks.add(t)
                t.add_done_callback(_tasks.discard)

            await asyncio.to_thread(client.delete_notification, receipt_id)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.exception("Polling error: %s", e)
            await asyncio.sleep(5)