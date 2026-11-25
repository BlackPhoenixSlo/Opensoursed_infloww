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

