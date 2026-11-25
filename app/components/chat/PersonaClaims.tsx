"use client";


import { useEffect, useState } from "react";

import { useAccountConfig } from "@/hooks/useAccountConfig";
import { MP } from "@/lib/messagesPro";
import type { FanRecord, PersonaClaim, ResolvedClaim } from "@/lib/relay";
import { cn } from "@/lib/utils";

const O = MP.ours.PersonaClaims;

type ClaimColumn = NonNullable<ResolvedClaim["column"]>;

export interface CanonFact { key: string; label: string; value: string }

export function canonFacts(
  facts: Record<string, string> | undefined,
  fields: { key: string; label: string }[] | undefined,
): CanonFact[] {
  const f = facts ?? {};
  return (fields ?? [])
    .filter((fld) => (f[fld.key] ?? "").trim() !== "")
    .map((fld) => ({ key: fld.key, label: fld.label, value: f[fld.key] }));
}

export function claimDate(at: string | null | undefined): string {
  if (!at) return "";
  const d = new Date(at);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString();
}

export function visibleClaims(claims: PersonaClaim[] | undefined): PersonaClaim[] {
  return (claims ?? []).filter((c) => (c?.claim ?? "").trim() !== "");
}

export function visibleResolved(rows: ResolvedClaim[] | undefined): ResolvedClaim[] {
  return (rows ?? []).filter((r) => (r?.value ?? "").trim() !== "");
}

export function supersededClaims(
  claims: PersonaClaim[] | undefined, resolved: ResolvedClaim[] | undefined,
): PersonaClaim[] {
  const current = new Set(visibleResolved(resolved).map((r) => r.value.trim()));
  return visibleClaims(claims).filter((c) => !current.has((c.claim ?? "").trim()));
}

export function PersonaClaims({
  accountId, fan, onSave,
}: {
  accountId: string;
  fan: FanRecord;
  onSave: (patch: Partial<Record<ClaimColumn, string | null>>) => void;
}) {
  const rows = visibleResolved(fan.persona_claims_resolved);
  const older = supersededClaims(fan.persona_claims, fan.persona_claims_resolved);

  const cfgQ = useAccountConfig(accountId);
  const canon = canonFacts(cfgQ.data?.config?.persona_facts,
                           cfgQ.data?.persona_fact_fields);

  return (
    <div className="space-y-3 border-t border-border pt-3">
      <details className="group">
        <summary className="flex cursor-pointer items-baseline justify-between gap-2 list-none">
          <span className={cn(O.heading, "uppercase text-fg-dim group-hover:text-fg")}>
            Creator facts · in every prompt
          </span>
          <span className={cn(O.small, "text-fg-dim tabular-nums")}>
            {canon.length || (cfgQ.isLoading ? "…" : "none set")}
          </span>
        </summary>
        {canon.length === 0 ? (
          <p className={cn(O.canonEmpty, "text-fg-dim")}>
            No facts pinned for this model, so every answer about the creator is
            improvised — and each one lands in the list below instead. Fill them
            once under Automations → the brain (🪄 Enrich proposes them).
          </p>
        ) : (
          <ul className="mt-1.5 space-y-1">
            {canon.map((c) => (
              <li key={c.key} className={O.line}>
                <span className="text-fg-dim">{c.label}: </span>
                <span className="text-fg">{c.value}</span>
              </li>
            ))}
          </ul>
        )}
      </details>

      <div className="space-y-2">
      <div className="flex items-baseline justify-between gap-2">
        <span className={cn(O.heading, "uppercase text-fg-dim")}>
          What this fan was told
        </span>
        {rows.length > 0 && (
          <span className={cn(O.small, "text-fg-dim tabular-nums")}>{rows.length}</span>
        )}
      </div>

      {rows.length === 0 ? (
        <p className={cn(O.text, "text-fg-dim")}>
          This fan hasn&apos;t been told anything about the creator yet. Whatever gets
          said is pinned here, so he can&apos;t be given a different version later.
        </p>
      ) : (
        <ul className="space-y-1.5">
          {rows.map((r) => (
            <ClaimRow
              key={`${r.label}-${r.at ?? ""}`}
              row={r}
              onCommit={(next) => r.column && onSave({ [r.column]: next || null })}
            />
          ))}
        </ul>
      )}

      {older.length > 0 && (
        <details className="pt-0.5">
          <summary className={cn(O.text, "cursor-pointer text-fg-dim hover:text-fg")}>
            Earlier versions given ({older.length})
          </summary>
          <ul className="mt-1.5 space-y-1">
            {older.map((c, i) => (
              <li key={`${c.topic ?? "claim"}-${c.at ?? i}`}
                  className={cn(O.line, "text-fg-dim line-through decoration-fg-dim/40")}>
                {c.topic ?? "about the creator"}: {c.claim}
                {claimDate(c.at) && <span className="ml-1 tabular-nums">· {claimDate(c.at)}</span>}
              </li>
            ))}
          </ul>
        </details>
      )}

      {rows.length > 0 && (
        <p className={cn(O.small, "hidden md:block text-fg-dim")}>
          This is exactly what the prompt is given. Rows with a pencil can be
          corrected — the rest are recorded as they were said.
        </p>
      )}
      </div>
    </div>
  );
}

function ClaimRow({
  row, onCommit,
}: {
  row: ResolvedClaim;
  onCommit: (next: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(row.value);

  // Switching fans reuses this component; a stale draft would show the previous fan's claim.
  useEffect(() => { setDraft(row.value); setEditing(false); }, [row.value]);

  if (editing) {
    return (
      <li>
        <span className={cn(O.editLabel, "block uppercase text-fg-dim")}>{row.label}</span>
        <input
          autoFocus
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => {
            setEditing(false);
            const next = draft.trim();
            if (next !== row.value.trim()) onCommit(next);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") e.currentTarget.blur();
            if (e.key === "Escape") { setDraft(row.value); setEditing(false); }
          }}
          className="w-full bg-bg border border-border rounded-md px-2 py-1 text-base md:text-sm focus:outline-none focus:border-accent"
        />
      </li>
    );
  }

  return (
    <li className={cn(O.row, "flex items-baseline")}>
      <span className="text-fg-dim shrink-0">{row.label}:</span>
      <span className="text-fg break-words min-w-0">{row.value}</span>
      {claimDate(row.at) && (
        <span className="text-fg-dim tabular-nums shrink-0">· {claimDate(row.at)}</span>
      )}
      {row.column && (
        <button
          type="button"
          onClick={() => setEditing(true)}
          title={`Correct what this fan was told — this is what the prompt reads`}
          aria-label={`Correct ${row.label}`}
          className="ml-auto shrink-0 text-fg-dim hover:text-[var(--inf-accent-text,var(--color-accent))] focus:outline-none focus:text-[var(--inf-accent-text,var(--color-accent))]"
        >
          ✎
        </button>
      )}
    </li>
  );
}
