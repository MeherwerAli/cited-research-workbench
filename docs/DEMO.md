# Two-to-three-minute demo script

1. Start the Compose topology and show all three services healthy.
2. Run `cd backend && uv run python scripts/demo.py` to ingest the fixed two-page public-safe PDF.
3. Point out that the answer cites the page-two chunk and that the audit sequence is persisted.
4. In the UI, start an estimated USD 0.11 run. Show `awaiting_approval`, approve it, then show the resumable event timeline.
5. Disconnect/reconnect the browser briefly and explain `Last-Event-ID` recovery.
6. Close with the explicit limits: no OCR, a 25 MB/200-page cap, a bounded public corpus, and no claim of universal prompt-injection prevention.

The recorded video remains a publication gate; this script is the reproducible local path.
