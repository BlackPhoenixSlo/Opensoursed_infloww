import { describe, expect, it } from "vitest";

import {
  employeesModalReducer, initialEmployeesModal,
  type EmployeesModal, type EmployeesModalAction, type EmployeesModalState,
} from "./employeesModalReducer";
import type { Employee } from "@/lib/relay";

const E = { id: 7, display_name: "Emp", is_active: true } as Employee;
const INV_A = { token: "a", expires_at: "2026-11-01T00:00:00Z", accept_path: "/chatter-login?token=a" };
// A resend of "a" again: the relay mints a new token, and "a" stops working.
const INV_A2 = { token: "a2", expires_at: "2026-11-01T00:00:00Z", accept_path: "/chatter-login?token=a2" };
const INV_B = { token: "b", expires_at: "2026-11-01T00:00:00Z", accept_path: "/chatter-login?token=b" };
// Each dialog is one value; `close` names that value (identity), as EmployeesTab's onClose does.
const ADD: EmployeesModal = { kind: "add" };
const EDIT_X: EmployeesModal = { kind: "edit", e: E };
const EDIT_Y: EmployeesModal = { kind: "edit", e: { ...E, id: 8 } };
const ROLE: EmployeesModal = { kind: "role", e: E };
const ACCESS: EmployeesModal = { kind: "access", e: E };
const ASSIGN: EmployeesModal = { kind: "batch", action: "Assign" };
const SHOWN = (invite: typeof INV_A): EmployeesModal => ({ kind: "invite", invite });
const open = (modal: EmployeesModal): EmployeesModalAction => ({ type: "open", modal });
const resent = (invite: typeof INV_A): EmployeesModalAction => ({ type: "inviteResent", invite });
const close = (modal: EmployeesModal): EmployeesModalAction => ({ type: "close", modal });
const run = (actions: EmployeesModalAction[], from: EmployeesModalState = initialEmployeesModal) =>
  actions.reduce(employeesModalReducer, from);

describe("employeesModalReducer — one dialog at a time", () => {
  it.each<[string, EmployeesModalAction[], EmployeesModalState]>([
    ["open shows it", [open(ROLE)], { modal: ROLE, queued: null }],
    ["open replaces a row modal (Edit over Set role)", [open(ROLE), open(EDIT_X)], { modal: EDIT_X, queued: null }],
    ["a Batch dialog replaces a row modal", [open(ACCESS), open(ASSIGN)], { modal: ASSIGN, queued: null }],
    ["a row modal replaces a Batch dialog", [open(ASSIGN), open(ADD)], { modal: ADD, queued: null }],
    ["close closes", [open(ADD), close(ADD)], { modal: null, queued: null }],
    ["close with nothing open is a no-op", [close(EDIT_X)], { modal: null, queued: null }],
    ["late Edit X close leaves Edit Y open", [open(EDIT_X), open(EDIT_Y), close(EDIT_X)],
      { modal: EDIT_Y, queued: null }],
    ["late batch close leaves newer Edit open", [open(ASSIGN), open(EDIT_X), close(ASSIGN)],
      { modal: EDIT_X, queued: null }],
    ["a late close keeps a waiting invite link waiting", [open(EDIT_X), resent(INV_A), close(ASSIGN)],
      { modal: EDIT_X, queued: INV_A }],
    ["a resend with nothing open shows its link", [resent(INV_A)], { modal: SHOWN(INV_A), queued: null }],
    ["a resend landing on an open modal waits; the modal stays", [open(EDIT_X), resent(INV_A)],
      { modal: EDIT_X, queued: INV_A }],
    ["…and shows when that modal closes", [open(EDIT_X), resent(INV_A), close(EDIT_X)],
      { modal: SHOWN(INV_A), queued: null }],
    ["a newer resend replaces a queued one (one slot)", [open(ASSIGN), resent(INV_A), resent(INV_B), close(ASSIGN)],
      { modal: SHOWN(INV_B), queued: null }],
    ["a resend over an open invite link replaces it", [resent(INV_A), resent(INV_B)],
      { modal: SHOWN(INV_B), queued: null }],
    ["re-resending the shown invite shows only its fresh link (the shown one died)", [resent(INV_A), resent(INV_A2)],
      { modal: SHOWN(INV_A2), queued: null }],
  ])("%s", (_name, actions, want) => {
    expect(run(actions)).toEqual(want);
  });

  it("a shown invite link then closes like any other (by the value shown)", () => {
    const shown = run([open(EDIT_X), resent(INV_A), close(EDIT_X)]);
    expect(employeesModalReducer(shown, close(shown.modal!))).toEqual({ modal: null, queued: null });
  });
});
