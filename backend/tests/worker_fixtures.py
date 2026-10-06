"""Controlled collector used only by worker/persistence tests; never production code."""

import asyncio
import hashlib
from datetime import UTC, datetime

from app.collector.amazon import AmazonCollector
from app.collector.base import EvidenceArtifactData
from app.models.schemas import ExtractedProduct, ExtractedSearchCandidate, ProvenanceMetadata


class FixtureCollector(AmazonCollector):
    def __init__(self, settings):
        super().__init__(settings)
        self.entered = 0
        self.closed = False
        self.calls = []
        self.failure = None
        self.candidate_failure = None
        self.search_failure = None
        self.startup_failure = None
        self.started = asyncio.Event()
        self.release = None
        self.cancelled = False
        self.product_mutator = None

    async def __aenter__(self):
        self.entered += 1
        if self.startup_failure:
            raise self.startup_failure
        return self

    async def __aexit__(self, *_):
        self.closed = True

    def capture(self, url, body):
        content = body.encode()
        digest = hashlib.sha256(content).hexdigest()
        path = self.settings.evidence_dir / f"{digest}.html"
        path.write_bytes(content)
        return EvidenceArtifactData(
            digest, path.name, len(content), url, "playwright_amazon", datetime.now(UTC)
        )

    async def collect_product(self, asin, domain, requested_location=None):
        self.calls.append((asin, domain, requested_location))
        self.started.set()
        if self.release is not None:
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        if self.failure:
            raise self.failure
        if self.candidate_failure and asin == "B000000003":
            raise self.candidate_failure
        url = f"https://www.amazon.{domain}/dp/{asin}"
        evidence = self.capture(url, f"<html><h1>Fixture {asin}</h1><span>$10.12</span></html>")
        product = ExtractedProduct(
            asin=asin,
            domain=domain,
            title=f"Fixture {asin}",
            brand="Fixture",
            price_text="$10.12",
            price_amount="10.12",
            currency="USD",
            provenance=ProvenanceMetadata(
                source_url=url,
                timestamp=evidence.captured_at,
                collector=evidence.collector,
                extraction_method="json_ld",
                evidence_id=evidence.content_hash,
            ),
        )
        if self.product_mutator:
            product = self.product_mutator(product, evidence)
        return product, evidence

    async def search_competitors(self, query, domain, max_pages=1):
        self.search_evidence = [
            self.capture(
                f"https://www.amazon.{domain}/s?k=fixture&page={page}",
                f"<html>Search page {page}</html>",
            )
            for page in range(1, max_pages + 1)
        ]
        self.search_candidates = []
        for rank, (asin, sponsored) in enumerate(
            (
                ("B09XS7JWHH", False),
                ("B000000002", False),
                ("B000000002", False),
                ("B000000003", False),
                ("B000000004", True),
            ),
            1,
        ):
            evidence = self.search_evidence[(rank - 1) % len(self.search_evidence)]
            self.search_candidates.append(
                ExtractedSearchCandidate(
                    asin=asin,
                    title=f"Fixture {asin}",
                    rank=rank,
                    sponsored=sponsored,
                    detail_url=f"https://www.amazon.{domain}/dp/{asin}",
                    provenance=ProvenanceMetadata(
                        source_url=evidence.source_url,
                        timestamp=evidence.captured_at,
                        collector=evidence.collector,
                        extraction_method="search_card_dom",
                        evidence_id=evidence.content_hash,
                    ),
                )
            )
        if self.search_failure:
            raise self.search_failure
        return self.search_candidates, self.search_evidence[-1]
