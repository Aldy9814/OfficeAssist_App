from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import os

from pydantic import BaseModel
from datetime import datetime
from weasyprint import HTML
from jinja2 import Environment, FileSystemLoader, select_autoescape
from firebase_admin import firestore

router = APIRouter(prefix="/disposisi", tags=["Surat Disposisi"])
templates = Jinja2Templates(directory="templates")

OUTPUT_DIR = "uploads/disposisi"
os.makedirs(OUTPUT_DIR, exist_ok=True)

env = Environment(
    loader=FileSystemLoader("templates"),
    autoescape=select_autoescape(['html'])
)

class DispositionData(BaseModel):
    document_number: str
    document_date: str
    subject: str

@router.get("/download/{filename}")
async def download_pdf(filename: str):
    file_path = os.path.join(OUTPUT_DIR, filename)
    if os.path.exists(file_path):
        return FileResponse(
            path=file_path,
            filename=filename,
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    raise HTTPException(status_code=404, detail="File not found")

@router.post("/api/generate")
async def generate_pdf(data: DispositionData, request: Request):
    try: 
        template = env.get_template('template_disposisi.html')

        html_out = template.render(
            no_suret=data.document_number,
            tgl_surat=data.document_date,
            perihal=data.subject
        )

        safe_doc_number = data.document_number.replace("/", "_").replace(" ", "")
        temp_pdf = f"Disposition_{safe_doc_number}.pdf"
        pdf_path = os.path.join(OUTPUT_DIR, temp_pdf)

        HTML(string=html_out, base_url="templates").write_pdf(pdf_path)

        base_url = str(request.base_url)
        pdf_url = f"{base_url}disposisi/download/{temp_pdf}"

        db = firestore.client()
        doc_ref = db.collection("disposition_history").document()
        doc_ref.set({
            "document_number": data.document_number,
            "document_date": data.document_date,
            "subject": data.subject,
            "pdf_url": pdf_url,
            "created_at": datetime.now()
        })

        return {"status": "success", "pdf_url": pdf_url}

    except Exception as e:
        print(f"Error Weasyprint/Firebase: {e}")
        raise HTTPException(status_code=500, detail=str(e))