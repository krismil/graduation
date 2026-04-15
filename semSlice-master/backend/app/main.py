from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router as api_router
from app.store.database import init_db
from app.store.repository import seed_default_users


app = FastAPI(
    title="SemSlice Front-Back Platform",
    version="0.1.0",
    description="Front-end/back-end separated platform for semantic communication slicing.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")


@app.on_event("startup")
def startup() -> None:
    init_db()
    seed_default_users()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
