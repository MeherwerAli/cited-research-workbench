import {describe, expect, it} from "vitest";

import {initialState, reduce} from "../lib/state";

describe("workbench reducer", () => {
  it("deduplicates replayed SSE events and keeps order", () => {
    const second = {id: 2, event_type: "run.executing", state: "executing" as const, actor: "system", created_at: "now"};
    const first = {id: 1, event_type: "run.created", state: "draft" as const, actor: "requester", created_at: "now"};
    const state = reduce(reduce(reduce(initialState, {type: "event", event: second}), {type: "event", event: first}), {type: "event", event: second});
    expect(state.events.map((event) => event.id)).toEqual([1, 2]);
  });

  it("makes reconnecting state explicit", () => {
    expect(reduce(initialState, {type: "connection", connection: "reconnecting"}).connection).toBe("reconnecting");
  });
});
