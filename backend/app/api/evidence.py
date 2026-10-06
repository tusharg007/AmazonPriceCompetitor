"""Stored provenance metadata and integrity-checked evidence downloads."""

from uuid import UUID

from fastapi import APIRouter, Response

from app.api.products import Catalog
from app.models.schemas import EvidenceArtifactRead

router = APIRouter(prefix="/evidence", tags=["evidence"])


@router.get("/{evidence_id}", response_model=EvidenceArtifactRead)
async def evidence(evidence_id: UUID, service: Catalog) -> EvidenceArtifactRead:
    return await service.evidence(evidence_id)


@router.get(
    "/{evidence_id}/content",
    response_class=Response,
    responses={
        200: {
            "description": "Original verified evidence bytes",
            "content": {"text/html": {}, "image/png": {}, "application/json": {}},
        }
    },
)
async def content(evidence_id: UUID, service: Catalog) -> Response:
    data, media_type = await service.content(evidence_id)
    return Response(
        content=data,
        media_type=media_type,
        headers={
            "Content-Disposition": "attachment",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox; default-src 'none'",
            "Cache-Control": "no-store",
        },
    )
