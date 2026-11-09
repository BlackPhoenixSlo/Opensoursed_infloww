/**
 * VaultPackPickerModal's status line as a pure reducer: the request in flight (`busy`, shown instead of the note),
 * the last request's result (`note`, red when it `failed`) and how many items the last publish left on OF that their
 * rung no longer holds (`stale`, the warning icon). Save, Publish and Publish all each run start →
 * ok | fail; a start drops the previous note and warning.
 */

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
