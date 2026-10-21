"use client";

/**
 * Settings → System: the deployment master's ops back-office (users.is_admin only).
 *
 *   - the server's house keys and other agencies' keys (the founder cards from /creators, mounted as-is);
 *   - every account × automation: rule on/off vs config on/off, a disagreement highlighted
 *     (GET /admin/system/automations), plus the env kill switches;
 *   - the recent run log and failed / pending jobs across all accounts (GET /admin/system/runs).
 *
 * Read-only for automations: no toggles here. Hidden from the Tab list for everyone else (nav.ts
 * `masterOnly`), and a direct URL by anyone else is a 404, never this Panel. The relay gates both routes
 * with require_master regardless; this hiding is UI hygiene, not the gate.
 */

import { useQuery } from "@tanstack/react-query";
import { notFound } from "next/navigation";
import { useState } from "react";

import KeysCard from "@/components/setup/KeysCard";
import ManagedAgencyKeysCard from "@/components/setup/ManagedAgencyKeysCard";
import {
  FieldSelect, LoadError, Section, SettingsPanel, SettingsTable, TABLE_CELL, TABLE_ROW,
} from "@/components/settings/SettingsPanel";
import { useUser } from "@/contexts/UserContext";
import { relay } from "@/lib/relay";
import { cn } from "@/lib/utils";

interface AutomationState {
  kind: string;
  label: string;
  source: "rule+config" | "config" | "rule";
  rule_ids: number[];
  rule_enabled: boolean | null;
  rules_enabled_count: number;
  duplicate_rules: boolean;
  config_column: string | null;
  config_enabled: boolean | null;
  config_flags: Record<string, boolean>;
  config_stored: boolean;
  effective: boolean;
  mismatch: boolean;
}
interface SystemAutomations {
  accounts: { account_id: string; nickname: string | null; automations: AutomationState[] }[];
  kill_switches: { env: string; value: string | null; active: boolean; effect: string }[];
  mismatch_count: number;
}
interface SystemRuns {
  runs: {
    id: number; account_id: string | null; kind: string; status: string;
    started_at: string | null; completed_at: string | null; stats_json: string | null; error_text: string | null;
  }[];
  jobs: {
    id: number; account_id: string; kind: string; status: string;
    run_at: string | null; attempts: number; rule_id: number | null; last_error: string | null;
  }[];
}

const STATUSES = [
  { value: "", label: "Any status" },
  { value: "ok", label: "ok" },
  { value: "error", label: "error" },
  { value: "skipped", label: "skipped" },
  { value: "running", label: "running" },
  { value: "pending", label: "pending (jobs)" },
] as const;
type Status = (typeof STATUSES)[number]["value"];

const DIM = "text-[var(--if-fg-3)]";
const BAD = "text-[var(--if-danger)] font-medium";
const ON = "text-[var(--if-accent)]";
const BTN =
  "h-8 px-3 rounded-[var(--if-input-radius)] border border-[var(--if-line)] text-[length:var(--if-fs)] text-[var(--if-fg)] hover:border-[var(--if-accent)] disabled:opacity-50";

function when(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

const onOff = (v: boolean | null) => (v === null ? "none" : v ? "on" : "off");

/** One matrix cell: the short state, the mismatch in the danger colour, details in the title. */
function Cell({ a }: { a: AutomationState | undefined }) {
  if (!a) return <span className={DIM}>—</span>;
  const title = [
    a.rule_ids.length ? `rules ${a.rule_ids.join(", ")} (${a.rules_enabled_count} enabled)` : "no rule",
    a.config_column
      ? `${a.config_column}${a.config_stored ? "" : " (not saved, defaults)"}: ${Object.entries(a.config_flags)
          .map(([k, v]) => `${k}=${v}`)
          .join(", ")}`
      : "no config",
  ].join("\n");
  let text: string;
  let cls: string;
  if (a.mismatch) {
    text = `rule ${onOff(a.rule_enabled)} / cfg ${onOff(a.config_enabled)}`;
    cls = BAD;
  } else if (a.effective) {
    text = "on";
    cls = ON;
  } else {
    text = a.rule_ids.length || a.config_stored ? "off" : "—";
    cls = DIM;
  }
  return (
    <span title={title} className={cls}>
      {text}
      {a.duplicate_rules && <span className={cn(BAD, "ml-1")}>×{a.rule_ids.length}</span>}
    </span>
  );
}

function AutomationsSection() {
  const q = useQuery({
    queryKey: ["system-automations"],
    queryFn: () => relay.get<SystemAutomations>("/admin/system/automations"),
    staleTime: 30_000,
    retry: false,
  });
  const accounts = q.data?.accounts ?? [];
  // Columns: every kind any account reports, in the relay's order.
  const kinds: { kind: string; label: string }[] = [];
  for (const acct of accounts)
    for (const a of acct.automations) if (!kinds.some((k) => k.kind === a.kind)) kinds.push({ kind: a.kind, label: a.label });

  return (
    <>
      <Section title="Kill switches (env)">
        <LoadError error={q.error} />
        <SettingsTable columns={["Env", "Value", "State", "Turns off"]} small>
          {(q.data?.kill_switches ?? []).map((k) => (
            <tr key={k.env} className={TABLE_ROW}>
              <td className={cn(TABLE_CELL, "font-mono")}>{k.env}</td>
              <td className={TABLE_CELL}>{k.value ?? <span className={DIM}>unset</span>}</td>
              <td className={cn(TABLE_CELL, k.active ? BAD : DIM)}>{k.active ? "ACTIVE" : "inactive"}</td>
              <td className={TABLE_CELL}>{k.effect}</td>
            </tr>
          ))}
        </SettingsTable>
      </Section>
      <Section title="Automations on / off">
        <div className="mb-3 flex items-center gap-3 text-[length:var(--if-fs-sm)]">
          <span className={q.data?.mismatch_count ? BAD : DIM}>
            {q.data ? `${q.data.mismatch_count} rule/config mismatch(es)` : q.isLoading ? "Loading…" : ""}
          </span>
          <span className={DIM}>Hover a cell for rule ids and config flags. ×N = duplicate rules.</span>
          <button type="button" className={cn(BTN, "ml-auto")} onClick={() => q.refetch()} disabled={q.isFetching}>
            Refresh
          </button>
        </div>
        <SettingsTable columns={["Account", ...kinds.map((k) => k.label)]} small>
          {accounts.map((acct) => (
            <tr key={acct.account_id} className={TABLE_ROW}>
              <td className={TABLE_CELL} title={acct.account_id}>
                {acct.nickname ?? acct.account_id}
              </td>
              {kinds.map((k) => (
                <td key={k.kind} className={TABLE_CELL}>
                  <Cell a={acct.automations.find((a) => a.kind === k.kind)} />
                </td>
              ))}
            </tr>
          ))}
        </SettingsTable>
      </Section>
    </>
  );
}

function RunsSection() {
  // The kind box applies on Enter or Refresh, not per keystroke.
  const [draft, setDraft] = useState("");
  const [kind, setKind] = useState("");
  const [status, setStatus] = useState<Status>("");
  const params = new URLSearchParams({ limit: "100" });
  if (kind.trim()) params.set("kind", kind.trim());
  if (status) params.set("status", status);
  const qs = params.toString();
  const q = useQuery({
    queryKey: ["system-runs", qs],
    queryFn: () => relay.get<SystemRuns>(`/admin/system/runs?${qs}`),
    staleTime: 15_000,
    retry: false,
  });

  return (
    <Section title="Run log">
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <input
          aria-label="Kind"
          placeholder="Kind (e.g. autoreply)"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && setKind(draft)}
          className="w-56 h-8 px-3 rounded-[var(--if-input-radius)] border border-[var(--if-line)] bg-[var(--if-bg)] text-[length:var(--if-fs)] text-[var(--if-fg)] outline-none focus:border-[var(--if-accent)]"
        />
        <FieldSelect aria-label="Status" value={status} options={STATUSES} onChange={setStatus} className="w-44" />
        <button
          type="button"
          className={BTN}
          onClick={() => (draft === kind ? q.refetch() : setKind(draft))}
          disabled={q.isFetching}
        >
          Refresh
        </button>
      </div>
      <LoadError error={q.error} />
      <SettingsTable columns={["Started", "Account", "Kind", "Status", "Error"]} small>
        {(q.data?.runs ?? []).map((r) => (
          <tr key={r.id} className={TABLE_ROW}>
            <td className={TABLE_CELL}>{when(r.started_at)}</td>
            <td className={TABLE_CELL}>{r.account_id ?? "—"}</td>
            <td className={TABLE_CELL}>{r.kind}</td>
            <td className={cn(TABLE_CELL, r.status === "error" && BAD)}>{r.status}</td>
            <td className={cn(TABLE_CELL, "max-w-[28rem] truncate")} title={r.error_text ?? undefined}>
              {r.error_text ?? ""}
            </td>
          </tr>
        ))}
      </SettingsTable>
      {q.data && q.data.runs.length === 0 && <p className={cn("mt-2", DIM)}>No runs match.</p>}

      <h4 className="mt-6 mb-2 text-[length:var(--if-fs)] font-[var(--if-fw-title)] text-[var(--if-fg)]">
        Failed and pending jobs
      </h4>
      <SettingsTable columns={["Run at", "Account", "Kind", "Status", "Attempts", "Last error"]} small>
        {(q.data?.jobs ?? []).map((j) => (
          <tr key={j.id} className={TABLE_ROW}>
            <td className={TABLE_CELL}>{when(j.run_at)}</td>
            <td className={TABLE_CELL}>{j.account_id}</td>
            <td className={TABLE_CELL}>{j.kind}</td>
            <td className={cn(TABLE_CELL, j.status !== "pending" && BAD)}>{j.status}</td>
            <td className={TABLE_CELL}>{j.attempts}</td>
            <td className={cn(TABLE_CELL, "max-w-[28rem] truncate")} title={j.last_error ?? undefined}>
              {j.last_error ?? ""}
            </td>
          </tr>
        ))}
      </SettingsTable>
      {q.data && q.data.jobs.length === 0 && <p className={cn("mt-2", DIM)}>No failed or pending jobs match.</p>}
    </Section>
  );
}

export default function SystemTab() {
  const { user, loading } = useUser();
  // Nothing is drawn (and nothing fetched) until the session is known; then anyone
  // but the master gets the 404 page, so the tab's existence is never confirmed.
  if (loading) return null;
  if (user?.is_admin !== true) notFound();
  return (
    <SettingsPanel title="System">
      <Section title="Server keys">
        <div className="space-y-6">
          <KeysCard />
          <ManagedAgencyKeysCard />
        </div>
      </Section>
      <AutomationsSection />
      <RunsSection />
    </SettingsPanel>
  );
}
