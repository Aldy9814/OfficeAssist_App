from typing import Optional
from fastapi import APIRouter
from services.broadcast_service import run_due
from services.wa_client import ConsoleClient

router = APIRouter(prefix="/broadcast-test", tags=["Broadcast Test"])

@router.get("/preview")
def preview(broadcast_id: Optional[int] = None):
    results = run_due(ConsoleClient(), dry_run=True, broadcast_id=broadcast_id, only_due=False)
    return {"dry_run": True, "count": len(results), "results": results}


@router.post("/simulate")
def simulate(broadcast_id: Optional[int] = None, update_status: bool = False):
    client = ConsoleClient()
    results = run_due(
        client,
        dry_run=False,
        broadcast_id=broadcast_id,
        only_due=broadcast_id is None,
        update_status=update_status, force=True
    )

    return {"update_status": update_status, "console_output": client.sent, "results": results}