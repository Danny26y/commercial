from fastapi import APIRouter
from app.api.v1.endpoints import chat, health

api_v1_router = APIRouter()

api_v1_router.include_router(chat.router, tags=["Chat Completions"])
api_v1_router.include_router(health.router, tags=["Health & Diagnostics"])
