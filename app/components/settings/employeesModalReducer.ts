/**
 * EmployeesTab's dialogs as one value: the five row/header modals, the three Batch dialogs and a resent invite's
 * link were three useStates (`openModal`, `batch`, `resent`) that could be open together.
 *
 *   • `open` replaces whatever is open (Edit clicked while Set role is open shows Edit alone).
 *   • `inviteResent`: a Resend answers after its click, so another dialog may be open by then. Its fresh link is the
 *     only one that works (the old one stopped). Nothing or an invite link open: shown at once (it replaces that
 *     link, so a resend of the same invite never shows the dead one first). Another dialog open: kept in ONE slot
 *     and shown when that dialog closes; a newer resend replaces it (that invite can be resent again).
 *   • `close` names the dialog it closes (the `modal` value it was opened with) and is a no-op when any other is
 *     open (a late close of Edit X never closes Edit Y; a Batch save landing late never closes an Edit opened
 *     since); it then shows the waiting invite link, if any.
 */

import type { Employee } from "@/lib/relay";
import type { InviteResp } from "@/components/employees/EmployeeModals";

export const BATCH_ACTIONS = ["Batch edit roles", "Assign", "Batch edit group"] as const;
export type BatchAction = (typeof BATCH_ACTIONS)[number];

export type EmployeesModal =
  | { kind: "add" }
  | { kind: "edit"; e: Employee }
  | { kind: "role"; e: Employee }
  | { kind: "password"; e: Employee }
  | { kind: "access"; e: Employee }
  | { kind: "batch"; action: BatchAction }
  | { kind: "invite"; invite: InviteResp };

export interface EmployeesModalState {
  modal: EmployeesModal | null;
  /** A resent invite's link waiting for the open dialog to close (one slot: the latest). */
  queued: InviteResp | null;
}

export type EmployeesModalAction =
  | { type: "open"; modal: EmployeesModal }
  | { type: "inviteResent"; invite: InviteResp }
  | { type: "close"; modal: EmployeesModal };

export const initialEmployeesModal: EmployeesModalState = { modal: null, queued: null };

export function employeesModalReducer(state: EmployeesModalState, action: EmployeesModalAction): EmployeesModalState {
  switch (action.type) {
    case "open":
      return { ...state, modal: action.modal };
    case "inviteResent":
      return state.modal === null || state.modal.kind === "invite"
        ? { ...state, modal: { kind: "invite", invite: action.invite } }
        : { ...state, queued: action.invite };
    case "close":
      if (state.modal !== action.modal) return state;
      return { modal: state.queued ? { kind: "invite", invite: state.queued } : null, queued: null };
  }
}

