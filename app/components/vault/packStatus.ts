export interface PackStatus {
  busy: string;
  note: string;
  failed: boolean;
  stale: number;
}

export type PackStatusAction =
  | { type: "start"; busy: string }
  | { type: "ok"; note: string; stale?: number }
  | { type: "fail"; note: string; stale?: number };

export const initialPackStatus: PackStatus = { busy: "", note: "", failed: false, stale: 0 };

export function packStatusReducer(state: PackStatus, action: PackStatusAction): PackStatus {
  switch (action.type) {
    case "start":
      return { busy: action.busy, note: "", failed: false, stale: 0 };
    case "ok":
    case "fail":
      return { busy: "", note: action.note, failed: action.type === "fail", stale: action.stale ?? 0 };
  }
}
