"use client";

import { useReducer, useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { IfButton, IfHelp, IfInput, IfLabel } from "@/components/ui/infloww";
import { relay } from "@/lib/relay";

import { afterWatchWrite } from "./leakKeys";
import {
  ALIAS_LANE_LABEL, ALIASES_MAX, aliasLane, buildPayload, canSubmit, INITIAL_FORM, isTrimmed, leakIdentityFormReducer, TRIMMED_NOTE,
  validate,
  type LeakIdentityPayload,
} from "./leakIdentityForm";
import type { LeakTrimmed } from "./leakCoverage";

export type IdentityStart = {
  username: string;
  verified: boolean;
  display_name: string;
  aliases?: string[];
  instagram?: string | null;
  x?: string | null;
};

export function IdentityForm({ creatorId, scopeAccountId, start, trimmed, onDone, onCancel }: {
  creatorId: string;
  scopeAccountId: string | null;
  start: IdentityStart;
  trimmed: LeakTrimmed[];
  onDone: () => void;
  onCancel: () => void;
}) {
  const qc = useQueryClient();
  const [state, dispatch] = useReducer(leakIdentityFormReducer, INITIAL_FORM,
    (init) => leakIdentityFormReducer(init, { type: "adopt", ...start }));
  const [alias, setAlias] = useState("");
  const errors = validate(state);
  const save = useMutation({
    mutationFn: (body: LeakIdentityPayload) =>
      relay.put<{ synced: boolean }>(`/admin/leaks/watches/${creatorId}`, body, { accountId: scopeAccountId }),
    onSuccess: () => {
      void afterWatchWrite(qc, creatorId);
      onDone();
    },
    onError: (e: Error) => {
      dispatch({ type: "saveFailed", message: e.message });
      void afterWatchWrite(qc, creatorId);
    },
  });
  const submit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (canSubmit(state) && !save.isPending) save.mutate(buildPayload(state));
  };
  const addAlias = () => {
    dispatch({ type: "addAlias", value: alias });
    setAlias("");
  };
  const skipped = state.aliases.filter((a) => isTrimmed(trimmed, "alias", a));
  const skipNote = (field: "instagram" | "x") => isTrimmed(trimmed, field, state[field]) && <IfHelp>{TRIMMED_NOTE}</IfHelp>;
  const fieldError = (text: string | undefined, shown: boolean) =>
    text && shown ? <IfHelp className="text-err">{text}</IfHelp> : null;

  return (
    <form onSubmit={submit} aria-label="Leak identity" className="flex max-w-[560px] flex-col gap-4">
      <div>
        <IfLabel htmlFor="leak-handle" required>Handle</IfLabel>
        <div className="flex gap-2">
          <IfInput
            id="leak-handle"
            value={state.username}
            readOnly={state.verified}
            onChange={(e) => dispatch({ type: "edit", field: "username", value: e.target.value })}
            className="w-full"
            autoComplete="off"
          />
          {state.verified && (
            <IfButton type="button" onClick={() => dispatch({ type: "edit", field: "username", value: "" })}>Clear</IfButton>
          )}
        </div>
        <IfHelp>{state.verified ? "Verified from the live session" : "Typed, not verified"}</IfHelp>
        {fieldError(errors.username, state.username !== "")}
      </div>
      <div>
        <IfLabel htmlFor="leak-display-name">Display name</IfLabel>
        <IfInput
          id="leak-display-name"
          value={state.display_name}
          onChange={(e) => dispatch({ type: "edit", field: "display_name", value: e.target.value })}
          className="w-full"
        />
        <IfHelp>Only used to confirm matches</IfHelp>
        {fieldError(errors.display_name, true)}
      </div>
      <div>
        <IfLabel htmlFor="leak-alias">Aliases (up to {ALIASES_MAX})</IfLabel>
        {state.aliases.length > 0 && (
          <ul className="mb-2 flex flex-col gap-1">
            {state.aliases.map((a, i) => (
              <li key={`${a}-${i}`} className="flex items-center gap-2 rounded bg-bg-elev-2 px-2 py-1 text-[14px]">
                <span className="min-w-0 break-all">{a}</span>
                <span className="ml-auto shrink-0 text-[13px] text-muted">{ALIAS_LANE_LABEL[aliasLane(a)]}</span>
                <IfButton type="button" variant="link" aria-label={`Remove ${a}`} onClick={() => dispatch({ type: "removeAlias", index: i })}>×</IfButton>
              </li>
            ))}
          </ul>
        )}
        <div className="flex gap-2">
          <IfInput
            id="leak-alias"
            value={alias}
            onChange={(e) => setAlias(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addAlias(); } }}
            className="w-full"
            autoComplete="off"
          />
          <IfButton type="button" onClick={addAlias} disabled={!alias.trim()}>Add alias</IfButton>
        </div>
        {skipped.length > 0 && <IfHelp>{TRIMMED_NOTE}: {skipped.join(", ")}</IfHelp>}
        {fieldError(errors.aliases, true)}
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <IfLabel htmlFor="leak-instagram">Instagram</IfLabel>
          <IfInput
            id="leak-instagram"
            value={state.instagram}
            onChange={(e) => dispatch({ type: "edit", field: "instagram", value: e.target.value })}
            className="w-full"
            autoComplete="off"
          />
          {skipNote("instagram")}
          {fieldError(errors.instagram, true)}
        </div>
        <div>
          <IfLabel htmlFor="leak-x">X</IfLabel>
          <IfInput
            id="leak-x"
            value={state.x}
            onChange={(e) => dispatch({ type: "edit", field: "x", value: e.target.value })}
            className="w-full"
            autoComplete="off"
          />
          {skipNote("x")}
          {fieldError(errors.x, true)}
        </div>
      </div>
      {state.error && <p role="alert" className="text-[14px] text-err">{state.error}</p>}
      <div className="flex gap-2">
        <IfButton type="submit" variant="primary" disabled={!canSubmit(state) || save.isPending}>Save</IfButton>
        <IfButton type="button" onClick={onCancel}>Cancel</IfButton>
      </div>
    </form>
  );
}
