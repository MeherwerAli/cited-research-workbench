# Threat and failure model

- PDF bytes are untrusted. Size, signature, encryption state, page count, and extracted-text availability are checked before indexing.
- Retrieved text is evidence, never execution authority. The gateway prompt separates instructions from evidence, while all external/network/export actions remain code-gated.
- Approval is a durable state transition. An expensive or external action cannot execute from `awaiting_approval`; duplicate approval and stale transitions return conflicts.
- Audit events store detail hashes rather than raw questions or document text.
- Qdrant outages are visible failures in the configured runtime. The deterministic in-memory retriever exists for tests and the bounded sandbox, not as evidence of Qdrant availability.
- Hybrid retrieval and reranking can return irrelevant passages. Golden-case evaluation and explicit abstention constrain the claim; they do not eliminate retrieval error.
