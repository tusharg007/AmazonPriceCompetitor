# Screenshots from the genuine local demo

Captured directly from the unmodified running V2 application on 7 October 2026,
using Chromium at a 1360px viewport with Asia/Kolkata display time. Frames were
selected through browser screenshot bounds; no values or UI elements were painted
into the images. No additional Amazon or Groq collection was needed for this task.

| Image | What it demonstrates |
| --- | --- |
| [dashboard.png](dashboard.png) | Genuine tracked listing, captured price and candidate count |
| [product-detail.png](product-detail.png) | Amazon India identity, metadata, ₹649 captured price and successful job |
| [competitor-comparison.png](competitor-comparison.png) | Subset of the 20 confirmed candidates, prices, deterministic scores and source controls |
| [price-analytics.png](price-analytics.png) | Decimal statistics and rank 16 of 21 with cohort median ₹599; insufficient history is explicitly shown |
| [evidence-provenance.png](evidence-provenance.png) | Original source URL, capture time, collector, file size, SHA-256 and verified attachment |
| [ai-analysis.png](ai-analysis.png) | Actual Groq interpretation with observation IDs, extraction method, evidence hashes and citation controls |

The baseline is `B098LMDXS6` on `amazon.in`, Campus Men Sl-Spr001 Sliders. It was
captured at 2026-10-07 01:45:20 IST (2026-10-06 20:15:20 UTC) in the default delivery
context. Its collection saved the baseline plus 20 candidate observations.

The saved analysis `2d194001-53a3-4dbe-9713-3fbdb23ac46a` contains 47 published claims:
7 generated interpretations and 40 deterministic comparisons. Generated numerical
prose was withheld, as shown in the analysis screenshot. This count is a demo result,
not an accuracy metric. A single baseline capture does not establish a price trend.

Screenshots are intentionally public documentation assets. The live database,
original captured HTML, local browser binaries, configuration and credentials
remain excluded from Git. A fresh checkout does not include the saved demo database.
