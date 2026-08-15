# ADR 0001: Preserve page citations as data

Status: accepted
Date: 2026-08-15

## Decision

Every chunk retains the PDF source hash, document ID, one-based page number, and deterministic chunk ID. The answer contract requires citations on every non-abstaining claim; rendering citations is not left to free-form model text.

## Consequences

- Digitally extracted pages are the supported ingestion boundary.
- OCR and layout-coordinate claims are out of scope.
- An answer can fail closed by abstaining when retrieval does not supply support.
