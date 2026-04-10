"""
nbt-parser — FastAPI service for parsing NBT schedule and casting PDFs.

Endpoints:
  GET  /health   — Health check
  POST /process  — Parse PDFs, create GCal events, return Discord previews
"""

import base64
import logging
import os
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from schedule_parser import is_schedule_pdf, parse_schedule_pdf
from casting_parser import parse_casting_pdf
from calendar_writer import create_events
from discord_preview import format_schedule_preview, format_casting_preview

# Configure logging
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("nbt-parser")

app = FastAPI(title="nbt-parser", version="1.0.0")

# Whether to skip GCal event creation (for testing)
SKIP_GCAL = os.environ.get("SKIP_GCAL", "").lower() in ("1", "true", "yes")


class PdfInput(BaseModel):
    filename: str
    base64: str  # noqa: N815 — matches n8n output format


class ProcessRequest(BaseModel):
    pdfs: list[PdfInput]
    sender: str = ""
    subject: str = ""


class ScheduleResult(BaseModel):
    events_created: int = 0
    your_events: int = 0
    preview: str = ""
    schedule_dates: list[str] = []
    gcal_skipped: bool = False
    errors: list[str] = []


class CastingResult(BaseModel):
    roster: list[dict] = []
    your_roles: list[str] = []
    show: str = ""
    preview: str = ""
    llm_used: bool = False
    errors: list[str] = []


class ProcessResponse(BaseModel):
    schedules: Optional[ScheduleResult] = None
    castings: Optional[CastingResult] = None
    pdf_types: list[str] = []
    errors: list[str] = []


@app.get("/health")
async def health():
    return {"status": "ok", "service": "nbt-parser", "version": "1.0.0"}


@app.post("/process", response_model=ProcessResponse)
async def process_pdfs(request: ProcessRequest):
    """
    Process PDF attachments from an email.

    Classifies each PDF as schedule or casting, then:
    - Schedule: parse events, create GCal events, generate Discord preview
    - Casting: LLM-extract roster, generate Discord preview
    """
    if not request.pdfs:
        raise HTTPException(status_code=400, detail="No PDFs provided")

    response = ProcessResponse()
    schedule_pdfs = []
    casting_pdfs = []

    # Classify and decode PDFs
    for pdf_input in request.pdfs:
        try:
            pdf_bytes = base64.b64decode(pdf_input.base64)
        except Exception as e:
            response.errors.append(f"Failed to decode {pdf_input.filename}: {str(e)}")
            continue

        if is_schedule_pdf(pdf_bytes):
            schedule_pdfs.append((pdf_input.filename, pdf_bytes))
            response.pdf_types.append("schedule")
        else:
            casting_pdfs.append((pdf_input.filename, pdf_bytes))
            response.pdf_types.append("casting")

    # Process schedule PDFs
    if schedule_pdfs:
        all_events = []
        all_filtered = []
        schedule_dates = []
        schedule_errors = []

        for filename, pdf_bytes in schedule_pdfs:
            try:
                result = parse_schedule_pdf(pdf_bytes, filename)
                all_events.extend(result["events"])
                all_filtered.extend(result["filtered_events"])
                if result["schedule_date"] not in schedule_dates:
                    schedule_dates.append(result["schedule_date"])
            except Exception as e:
                err = f"Failed to parse schedule {filename}: {str(e)}"
                logger.error(err)
                schedule_errors.append(err)

        # Create GCal events
        gcal_result = {"events_created": 0, "your_events": 0, "errors": [], "gcal_skipped": False}
        if all_events and not SKIP_GCAL:
            for sdate in schedule_dates:
                date_events = [e for e in all_events if e['start'].startswith(sdate)]
                date_filtered = [e for e in all_filtered if e['start'].startswith(sdate)]
                try:
                    result = create_events(date_events, date_filtered, sdate)
                    gcal_result["events_created"] += result.get("events_created", 0)
                    gcal_result["your_events"] += result.get("your_events", 0)
                    gcal_result["errors"].extend(result.get("errors", []))
                    if result.get("gcal_skipped"):
                        gcal_result["gcal_skipped"] = True
                except Exception as e:
                    err = f"GCal creation failed for {sdate}: {str(e)}"
                    logger.error(err)
                    gcal_result["errors"].append(err)
        elif SKIP_GCAL:
            gcal_result["gcal_skipped"] = True

        # Generate Discord preview
        preview = format_schedule_preview(
            events=all_events,
            filtered_events=all_filtered,
            schedule_date=schedule_dates[0] if schedule_dates else "",
            subject=request.subject,
        )

        response.schedules = ScheduleResult(
            events_created=gcal_result["events_created"],
            your_events=gcal_result["your_events"],
            preview=preview,
            schedule_dates=schedule_dates,
            gcal_skipped=gcal_result.get("gcal_skipped", False),
            errors=schedule_errors + gcal_result.get("errors", []),
        )

    # Process casting PDFs
    if casting_pdfs:
        all_roster = []
        all_your_roles = []
        casting_previews = []
        casting_errors = []
        llm_used = False

        for filename, pdf_bytes in casting_pdfs:
            try:
                result = parse_casting_pdf(pdf_bytes, filename)
                if result.get("roster"):
                    all_roster.extend(result["roster"])
                if result.get("your_roles"):
                    all_your_roles.extend(result["your_roles"])
                if result.get("llm_used"):
                    llm_used = True
                if result.get("error"):
                    casting_errors.append(result["error"])

                # Generate preview for this casting PDF
                preview = format_casting_preview(
                    roster=result.get("roster", []),
                    your_roles=result.get("your_roles", []),
                    show=result.get("show", filename),
                    notes=result.get("notes", ""),
                    raw_preview=result.get("preview", ""),
                )
                casting_previews.append(preview)

            except Exception as e:
                err = f"Failed to parse casting {filename}: {str(e)}"
                logger.error(err)
                casting_errors.append(err)

        response.castings = CastingResult(
            roster=all_roster,
            your_roles=list(set(all_your_roles)),
            show=casting_pdfs[0][0].replace('.pdf', '').replace('.PDF', '') if casting_pdfs else "",
            preview='\n---\n'.join(casting_previews),
            llm_used=llm_used,
            errors=casting_errors,
        )

    return response


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8002"))
    uvicorn.run(app, host="0.0.0.0", port=port)
