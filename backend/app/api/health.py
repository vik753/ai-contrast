"""Health check endpoint."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app import __version__

router = APIRouter()


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str


@router.get("/api/health")
async def health() -> HealthResponse:
    return HealthResponse(status="ok", version=__version__)
