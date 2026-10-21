"use client";

/**
 * A versioned Settings tab's effective date and history (roadmap W6 6.4, service/settings_api.py): the Sales and
 * Time tracking tabs save a new version effective from a chosen time, now by default, and every sale and Clock
 * event reads the version in effect at its own time. So a save from today leaves past figures alone, and a
 * backdated one recomputes what falls between its time and the next version, which the warning names.
 *
 * Infloww's words: "Set effective date", "Settings history", "Effective as of". As Infloww, a time later than now
 * is refused (FUTURE); the Relay refuses its save too.
 */

import type { SettingsVersion } from "@/lib/settingsBlob";
import { Section } from "@/components/settings/SettingsPanel";

/** `datetime-local` text (local wall time, minutes) for an instant. */
function localInput(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

const when = (iso: string) => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

const SMALL = "text-[length:var(--if-fs-sm)] leading-5";

/** Infloww's refusal of an effective time later than now (`settings0190`). */
const FUTURE = "The effective time start later than the current time, please reset it.";

export default function SettingsVersions({ effective, history, recomputes, also, editing = true }: {
  effective: { value: string | null; set: (at: string | null) => void };
  history: SettingsVersion[];
  /** What a backdated save recomputes, as a sentence's subject: "Sales credited to employees". */
  recomputes: string;
  /** A sentence after the backdate warning. */
  also?: string;
  /** The date field shows only while the tab is being edited. */
  editing?: boolean;
}) {
  const now = new Date();
  const at = effective.value;
  const atMs = at ? Date.parse(at) : null;
  const later = (iso: string | null) => iso !== null && atMs !== null && Date.parse(iso) > atMs;
  const future = atMs !== null && atMs > now.getTime();
  // The next version after the chosen time bounds what the save reaches (`history` is latest first).
  const next = at ? history.filter((h) => later(h.effective_from)).at(-1)?.effective_from ?? null : null;

  return (
    <>
      {editing && (
        <Section title="Set effective date">
          <label className={`flex flex-wrap items-center gap-2 text-[var(--if-fg-2)] ${SMALL}`}>
            Specify the date and time for the changes to take effect:
            <input
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
      {history.length > 0 && (
        <Section title="Settings history">
          <ul aria-label="Settings history" className={`flex flex-col gap-1 text-[var(--if-fg-2)] ${SMALL}`}>
            {history.slice(0, 5).map((h, i) => (
              <li key={`${h.effective_from}-${h.saved_at}-${i}`}>
                Effective as of {h.effective_from ? when(h.effective_from) : "the start"}
                <span className="text-[var(--if-fg-3)]"> · saved {when(h.saved_at)}</span>
                {h.in_effect && <span className="ml-2 font-semibold text-[var(--if-accent)]">In effect</span>}
              </li>
            ))}
          </ul>
        </Section>
      )}
    </>
  );
}
