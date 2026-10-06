"""Shared, read-only verification of locally captured evidence."""

import asyncio
import hashlib
from pathlib import Path

from app.core.config import Settings
from app.core.exceptions import EvidenceError
from app.models.schemas import EvidenceArtifactRead


async def read_verified_evidence(
    settings: Settings, artifact: EvidenceArtifactRead
) -> tuple[bytes, str]:
    media = {
        "html": "text/html",
        "screenshot": "image/png",
        "jsonld": "application/json",
        "metadata": "application/json",
    }.get(artifact.evidence_type)
    if media is None:
        raise EvidenceError("Unsupported evidence content type")
    root = settings.evidence_dir.resolve()
    path = Path(artifact.storage_path)
    path = (path if path.is_absolute() else root / path).resolve()
    if not path.is_relative_to(root):
        raise EvidenceError("Evidence path is outside configured storage")
    try:
        content = await asyncio.to_thread(path.read_bytes)
    except FileNotFoundError as exc:
        raise EvidenceError("Evidence content file is missing", 404) from exc
    except OSError as exc:
        raise EvidenceError("Evidence content cannot be read", 503) from exc
    if (
        len(content) != artifact.content_size_bytes
        or hashlib.sha256(content).hexdigest() != artifact.content_hash
    ):
        raise EvidenceError("Evidence content failed integrity verification")
    return content, media
