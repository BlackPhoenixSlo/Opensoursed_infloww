"use client";


import type { SettingsVersion } from "@/lib/settingsBlob";
import { Section } from "@/components/settings/SettingsPanel";
import { IfDateInput } from "@/components/ui/ifDateInput";
import { dateTimeKey as localInput } from "@/components/ui/ifDateValue";

const when = (iso: string) => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

const SMALL = "text-[length:var(--if-fs-sm)] leading-5";

const FUTURE = "The effective time start later than the current time, please reset it.";

export default function SettingsVersions({ effective, history, recomputes, also, editing = true, show = "both" }: {
  effective: { value: string | null; set: (at: string | null) => void };
  history: SettingsVersion[];
  recomputes: string;
  also?: string;
  editing?: boolean;
  show?: "date" | "history" | "both";
}) {
  const now = new Date();
  const at = effective.value;
  const atMs = at ? Date.parse(at) : null;
  const later = (iso: string | null) => iso !== null && atMs !== null && Date.parse(iso) > atMs;
  const future = atMs !== null && atMs > now.getTime();
  const next = at ? history.filter((h) => later(h.effective_from)).at(-1)?.effective_from ?? null : null;

  return (
    <>
      {editing && show !== "history" && (
        <Section title="Set effective date">
          <label className={`flex flex-wrap items-center gap-2 text-[var(--if-fg-2)] ${SMALL}`}>
            Specify the date and time for the changes to take effect:
            <IfDateInput
              type="datetime-local"
              aria-label="Effective date"
              max={localInput(now)}
              value={at ? localInput(new Date(at)) : localInput(now)}
              onChange={(e) => effective.set(e.target.value ? new Date(e.target.value).toISOString() : null)}
              className="h-8 px-2 rounded-[var(--if-input-radius)] border border-[var(--if-line)] bg-[var(--if-bg)] text-[var(--if-fg)]"
            />
            {at && (
              <button type="button" className="text-[var(--if-accent)]" onClick={() => effective.set(null)}>
                Now
              </button>
            )}
          </label>
          {future && <p role="alert" className={`mt-2 text-err ${SMALL}`}>{FUTURE}</p>}
          {at && !future && (
            <p role="note" className={`mt-2 text-warn ${SMALL}`}>
              Backdated: {recomputes} from {when(at)} {next ? `until ${when(next)}` : "until now"} will be recomputed
              with these settings. Earlier ones keep the settings they had.{also && ` ${also}`}
            </p>
          )}
        </Section>
      )}
      {history.length > 0 && show !== "date" && (
        <Section title="Settings history">
          <ul aria-label="Settings history" className={`flex flex-col gap-1 text-[var(--if-fg-2)] ${SMALL}`}>
            {history.slice(0, 5).map((h, i) => (
              <li key={`${h.effective_from}-${h.saved_at}-${i}`}>
                Effective as of {h.effective_from ? when(h.effective_from) : "the start"}
                <span className="text-[var(--if-fg-3)]"> · saved {when(h.saved_at)}</span>
                {h.in_effect && (
                  <span className="ml-2 inline-flex items-center h-5 px-2 rounded-full bg-ok/15 text-ok text-[11px] font-medium">
                    In effect
                  </span>
                )}
              </li>
            ))}
          </ul>
        </Section>
      )}
    </>
  );
}
