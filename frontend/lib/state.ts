import type {AuditEvent, ResearchRun} from "./types";

export interface WorkbenchState {
  run?: ResearchRun;
  events: AuditEvent[];
  connection: "idle" | "connected" | "reconnecting" | "closed";
}

export type Action =
  | {type: "run"; run: ResearchRun}
  | {type: "event"; event: AuditEvent}
  | {type: "connection"; connection: WorkbenchState["connection"]};

export const initialState: WorkbenchState = {events: [], connection: "idle"};

export function reduce(state: WorkbenchState, action: Action): WorkbenchState {
  if (action.type === "run") return {...state, run: action.run};
  if (action.type === "connection") return {...state, connection: action.connection};
  if (state.events.some((event) => event.id === action.event.id)) return state;
  return {
    ...state,
    events: [...state.events, action.event].sort((left, right) => left.id - right.id),
    run: state.run ? {...state.run, state: action.event.state} : state.run,
  };
}
