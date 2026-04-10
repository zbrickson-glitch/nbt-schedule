from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
from app.routers import ingest, backfill, casting, schedule, subscribers, ical_router, public
from app.routers.pipeline import router as pipeline_router

app = FastAPI(title="NBT Schedule Service", version="0.1.0")

app.include_router(ingest.router)
app.include_router(backfill.router)
app.include_router(casting.router)
app.include_router(schedule.router)
app.include_router(subscribers.router)
app.include_router(ical_router.router)
app.include_router(public.router)
app.include_router(pipeline_router)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "nbt-schedule-service"}


@app.get("/")
def serve_calendar():
    return FileResponse(str(static_dir / "index.html"))


@app.get("/sw.js")
def serve_sw():
    return FileResponse(str(static_dir / "sw.js"), media_type="application/javascript")


static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
