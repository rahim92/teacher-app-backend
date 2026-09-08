from fastapi import FastAPI

from app.database import init_db
from app.routers import academic, assessments, auth, council, curriculum, export, messaging, sessions, students, sync

app = FastAPI(title="Middle School Teacher App API")

# Called at import time (not only on the ASGI startup event) so the app also
# works correctly under test clients / tools that never fire startup events.
init_db()


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(auth.router)
app.include_router(academic.router)
app.include_router(students.router)
app.include_router(curriculum.router)
app.include_router(sessions.router)
app.include_router(assessments.router)
app.include_router(messaging.router)
app.include_router(export.router)
app.include_router(council.router)
app.include_router(sync.router)
