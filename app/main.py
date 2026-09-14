from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import init_db
from app.routers import academic, alerts, assessments, auth, behavior, council, curriculum, export, grades, messaging, sessions, students, sync

app = FastAPI(title="Middle School Teacher App API")

# Wide open on purpose: this API has no first-party web frontend of its own
# (the real client is the Flutter mobile app, which isn't subject to CORS).
# The only browser callers are developer tools -- Swagger UI and the
# standalone HTML test pages we hand out -- so there is no cookie/session
# to protect here (auth is a bearer JWT the caller attaches explicitly).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Called at import time (not only on the ASGI startup event) so the app also
# works correctly under test clients / tools that never fire startup events.
init_db()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/health/pdf-engine")
def health_pdf_engine():
    """TEMPORARY diagnostic -- checks whether WeasyPrint's native
    cairo/pango libraries are actually usable on THIS deployment (Render's
    free "python" native runtime, no Dockerfile, no apt-get in the build
    step), before building a real feature on top of it. `weasyprint` the
    PyPI package can install fine via pip while still failing at import/
    render time with an OSError if the underlying .so files aren't present
    on the host -- which `except ImportError` elsewhere in this codebase
    would NOT catch. To be removed once the answer is known either way."""
    try:
        from weasyprint import HTML

        pdf_bytes = HTML(string="<b>test</b>").write_pdf()
        return {"weasyprint_ok": True, "pdf_bytes": len(pdf_bytes)}
    except Exception as exc:  # noqa: BLE001 -- diagnostic route, want ANY failure surfaced
        return {"weasyprint_ok": False, "error_type": type(exc).__name__, "error": str(exc)}


app.include_router(auth.router)
app.include_router(academic.router)
app.include_router(students.router)
app.include_router(curriculum.router)
app.include_router(sessions.router)
app.include_router(assessments.router)
app.include_router(messaging.router)
app.include_router(export.router)
app.include_router(council.router)
app.include_router(behavior.router)
app.include_router(grades.router)
app.include_router(alerts.router)
app.include_router(sync.router)
