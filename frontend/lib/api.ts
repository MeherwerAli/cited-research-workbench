import type {AuditEvent, ResearchRun} from "./types";

const API_URL = process.env.NEXT_PUBLIC_WORKBENCH_API_URL ?? "http://localhost:8090";

async function checked<T>(response: Response | Promise<Response>): Promise<T> {
  const resolved = await response;
  if (!resolved.ok) {
    const body = await resolved.text();
    throw new Error(`${resolved.status}: ${body}`);
  }
  return resolved.json() as Promise<T>;
}

export async function uploadPdf(file: File): Promise<{id: string; page_count: number}> {
  const form = new FormData();
  form.append("file", file);
  return checked(fetch(`${API_URL}/v1/documents`, {method: "POST", body: form}));
}

export async function startRun(query: string, expensive: boolean): Promise<ResearchRun> {
  return checked(
    fetch(`${API_URL}/v1/research-runs`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        query,
        estimated_cost_usd: expensive ? "0.11" : "0",
        external_network: false,
        export_requested: false,
      }),
    }),
  );
}

export async function approveRun(runId: string): Promise<ResearchRun> {
  return checked(
    fetch(`${API_URL}/v1/research-runs/${runId}/approvals`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({actor: "portfolio-reviewer"}),
    }),
  );
}

export async function getRun(runId: string): Promise<ResearchRun> {
  return checked(fetch(`${API_URL}/v1/research-runs/${runId}`, {cache: "no-store"}));
}

export function observeRun(
  runId: string,
  onEvent: (event: AuditEvent) => void,
  onStatus: (status: "connected" | "reconnecting" | "closed") => void,
): () => void {
  const source = new EventSource(`${API_URL}/v1/research-runs/${runId}/events`);
  source.onopen = () => onStatus("connected");
  source.addEventListener("audit", (message) => {
    onEvent(JSON.parse((message as MessageEvent<string>).data) as AuditEvent);
  });
  source.onerror = () => onStatus("reconnecting");
  return () => {
    source.close();
    onStatus("closed");
  };
}
