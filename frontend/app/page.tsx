"use client";

import {FormEvent, useEffect, useReducer, useState} from "react";

import {approveRun, getRun, observeRun, startRun, uploadPdf} from "../lib/api";
import {initialState, reduce} from "../lib/state";

export default function Home() {
  const [state, dispatch] = useReducer(reduce, initialState);
  const [query, setQuery] = useState("What failure behavior does this document recommend?");
  const [expensive, setExpensive] = useState(false);
  const [documentStatus, setDocumentStatus] = useState("No PDF indexed");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!state.run) return;
    return observeRun(
      state.run.id,
      async (event) => {
        dispatch({type: "event", event});
        if (["completed", "failed", "cancelled"].includes(event.state)) {
          dispatch({type: "run", run: await getRun(state.run!.id)});
        }
      },
      (connection) => dispatch({type: "connection", connection}),
    );
  }, [state.run?.id]);

  async function onUpload(file?: File) {
    if (!file) return;
    setDocumentStatus("Indexing digital text…");
    setError("");
    try {
      const document = await uploadPdf(file);
      setDocumentStatus(`Indexed ${document.page_count} page${document.page_count === 1 ? "" : "s"}`);
    } catch (caught) {
      setDocumentStatus("Indexing failed");
      setError(caught instanceof Error ? caught.message : "Unknown upload error");
    }
  }

  async function onResearch(event: FormEvent) {
    event.preventDefault();
    setError("");
    try {
      dispatch({type: "run", run: await startRun(query, expensive)});
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unknown research error");
    }
  }

  async function onApprove() {
    if (!state.run) return;
    dispatch({type: "run", run: await approveRun(state.run.id)});
  }

  return (
    <main>
      <header>
        <span className="eyebrow">RELIABLE AI SYSTEMS / CASE STUDY 02</span>
        <h1>Cited Research Workbench</h1>
        <p className="lede">
          Page-specific evidence, explicit approval gates, and an append-only audit trail—before an
          agent is allowed to act.
        </p>
      </header>

      <section className="workspace" aria-label="Research workspace">
        <aside>
          <h2>1. Evidence</h2>
          <label className="upload">
            <span>Choose a digital-text PDF</span>
            <input type="file" accept="application/pdf" onChange={(event) => onUpload(event.target.files?.[0])} />
          </label>
          <p className="status">{documentStatus}</p>
          <p className="limit">25 MB · 200 pages · no OCR</p>

          <h2>2. Controls</h2>
          <label className="toggle">
            <input type="checkbox" checked={expensive} onChange={(event) => setExpensive(event.target.checked)} />
            <span>Simulate cost above approval threshold</span>
          </label>
          <dl>
            <div><dt>Stream</dt><dd>{state.connection}</dd></div>
            <div><dt>Run state</dt><dd>{state.run?.state ?? "idle"}</dd></div>
            <div><dt>Trace</dt><dd>{state.run?.trace_id.slice(0, 10) ?? "—"}</dd></div>
          </dl>
        </aside>

        <div className="research">
          <form onSubmit={onResearch}>
            <label htmlFor="question">Research question</label>
            <textarea id="question" value={query} onChange={(event) => setQuery(event.target.value)} minLength={3} required />
            <button type="submit">Start research</button>
          </form>

          {state.run?.state === "awaiting_approval" && (
            <div className="approval" role="alert">
              <div><strong>Approval required</strong><p>The estimated action exceeds the configured cost boundary.</p></div>
              <button onClick={onApprove}>Approve once</button>
            </div>
          )}

          {error && <p className="error" role="alert">{error}</p>}

          <article aria-live="polite">
            <div className="article-heading"><h2>Answer</h2><span>{state.run?.answer?.abstained ? "ABSTAINED" : "CITED"}</span></div>
            <p>{state.run?.answer?.answer ?? "The answer and page citations will appear here."}</p>
            {state.run?.answer?.claims.map((claim, index) => (
              <div className="claim" key={`${claim.text}-${index}`}>
                <p>{claim.text}</p>
                <ul>{claim.citations.map((citation) => <li key={citation.chunk_id}>Document {citation.document_id.slice(0, 12)} · page {citation.page}</li>)}</ul>
              </div>
            ))}
          </article>
        </div>
      </section>

      <section className="audit" aria-label="Audit trail">
        <div><span className="eyebrow">APPEND-ONLY EVIDENCE</span><h2>Audit trail</h2></div>
        <ol>{state.events.map((event) => <li key={event.id}><span>{event.id.toString().padStart(2, "0")}</span><strong>{event.event_type}</strong><small>{event.actor}</small></li>)}</ol>
      </section>
    </main>
  );
}
