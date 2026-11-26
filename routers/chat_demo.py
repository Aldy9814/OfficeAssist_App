from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import text

from services.chat_demo import REPORT_MIME, ChatError, resolve_report_file, run_chat
from services.dispatcher import _get_engine

router = APIRouter(prefix="/api/chat", tags=["Chat Demo"])

class ChatBody(BaseModel):
    sender: str
    text: str

@router.post("/send")
def chat_send(body: ChatBody):
    try:
        return run_chat(body.sender, body.text)
    except ChatError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/senders")
def chat_senders():
    with _get_engine().connect() as conn:
        rows = conn.execute(text(
            "SELECT employee_id, full_name, whatsapp_number, division FROM employees ORDER BY full_name"

        )).fetchall()
    return {"senders": [dict(r._mapping) for r in rows]}

@router.get("/file/{filename}")
def chat_file(filename: str):
    path = resolve_report_file(filename)
    if not path:
        raise HTTPException(status_code=404, detail="File tidak ditemukan")
    return FileResponse(path, filename=filename, media_type=REPORT_MIME)
