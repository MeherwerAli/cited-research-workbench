import io
import json
import os
import time

import httpx
from reportlab.pdfgen import canvas


def fixed_corpus() -> bytes:
    output = io.BytesIO()
    document = canvas.Canvas(output)
    document.drawString(
        72,
        750,
        "Bounded retries use exponential backoff and random jitter before terminal failure.",
    )
    document.showPage()
    document.drawString(
        72,
        750,
        "Idempotency keys prevent duplicate side effects when a safe request is retried.",
    )
    document.showPage()
    document.save()
    return output.getvalue()


def wait_for_terminal(client: httpx.Client, run_id: str) -> dict[str, object]:
    for _ in range(50):
        response = client.get(f"/v1/research-runs/{run_id}")
        response.raise_for_status()
        run = response.json()
        if run["state"] in {"completed", "failed", "cancelled"}:
            return run
        time.sleep(0.1)
    raise RuntimeError("research run did not become terminal within five seconds")


def main() -> None:
    base_url = os.getenv("WORKBENCH_DEMO_URL", "http://127.0.0.1:8090")
    with httpx.Client(base_url=base_url, timeout=20) as client:
        upload = client.post(
            "/v1/documents",
            files={"file": ("reliability-demo.pdf", fixed_corpus(), "application/pdf")},
        )
        upload.raise_for_status()
        document = upload.json()
        started = client.post(
            "/v1/research-runs",
            json={"query": "How do idempotency keys prevent duplicate side effects?"},
        )
        started.raise_for_status()
        run = wait_for_terminal(client, started.json()["id"])
        audit = client.get(f"/v1/research-runs/{run['id']}/audit")
        audit.raise_for_status()
    answer = run["answer"]
    assert isinstance(answer, dict)
    claims = answer["claims"]
    assert isinstance(claims, list) and claims
    print(
        json.dumps(
            {
                "document_id": document["id"],
                "page_count": document["page_count"],
                "run_id": run["id"],
                "state": run["state"],
                "abstained": answer["abstained"],
                "citations": claims[0]["citations"],
                "audit_events": [event["event_type"] for event in audit.json()],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
