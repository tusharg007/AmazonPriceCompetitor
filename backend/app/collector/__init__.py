"""Collector package exporting browser and Amazon collectors."""

from app.collector.amazon import AmazonCollector
from app.collector.base import (
    BrowserCollector,
    EvidenceArtifactData,
    PageNotFoundError,
    ScrapingBlockedError,
)

__all__ = [
    "AmazonCollector",
    "BrowserCollector",
    "EvidenceArtifactData",
    "PageNotFoundError",
    "ScrapingBlockedError",
]
