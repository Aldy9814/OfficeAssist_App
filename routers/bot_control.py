from fastapi import APIRouter
from pydantic import BaseModel

from services.settings import is_bot_enabled, set_bot_enabled

router = APIRouter(prefix="/api/bot", tags=["Bot Control"])

class ToggleBody(BaseModel):
    enabled: bool

@router.get("/status")
def bot_status():
    return {"enabled": is_bot_enabled(force=True)}

@router.post("/toggle")
def bot_toggle(body: ToggleBody):
    set_bot_enabled(body.enabled)
    return {"status": "success", "enabled": body.enabled}