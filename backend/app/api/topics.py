"""``GET /api/topics/catalog``: the static topic catalog (ADR 0017 point 2).

No request body, no key, no AI call. The reply is built once at startup.
"""

from __future__ import annotations

import json
from typing import Final

from fastapi import APIRouter, FastAPI, Request, Response

from app.topics.catalog import Catalog

CACHE_CONTROL: Final = "public, max-age=3600"

router = APIRouter()


@router.get("/api/topics/catalog")
async def get_catalog(request: Request) -> Response:
    body: bytes = request.app.state.catalog_body
    return Response(
        content=body, media_type="application/json", headers={"Cache-Control": CACHE_CONTROL}
    )


def catalog_of(request: Request) -> Catalog:
    """The catalog of the app (typed accessor of ``app.state``)."""
    catalog = getattr(request.app.state, "catalog", None)
    if not isinstance(catalog, Catalog):
        msg = "app state is not configured"
        raise TypeError(msg)
    return catalog


def install(app: FastAPI, catalog: Catalog) -> None:
    """Keep the catalog and its JSON body in the app state and register the route."""
    app.state.catalog = catalog
    app.state.catalog_body = json.dumps(
        catalog.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    app.include_router(router)
