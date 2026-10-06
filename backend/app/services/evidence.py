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
    if artifact.content_size_bytes > settings.max_evidence_bytes:
        raise EvidenceError("Evidence exceeds configured size limit", 413)

    def read() -> bytes:
        # Bounded read also handles files growing after a metadata/stat check.
        with path.open("rb") as file:
            return file.read(settings.max_evidence_bytes + 1)

    try:
        content = await asyncio.to_thread(read)
    except FileNotFoundError as exc:
        raise EvidenceError("Evidence content file is missing", 404) from exc
    except OSError as exc:
        raise EvidenceError("Evidence content cannot be read", 503) from exc
    if len(content) > settings.max_evidence_bytes:
        raise EvidenceError("Evidence exceeds configured size limit", 413)
    if (
        len(content) != artifact.content_size_bytes
        or hashlib.sha256(content).hexdigest() != artifact.content_hash
    ):
        raise EvidenceError("Evidence content failed integrity verification")
    return content, media
