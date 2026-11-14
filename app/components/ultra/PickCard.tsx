"use client";

/**
 * A `needs_you` judge's pick card (ultra ticket 06 owner amendment): its question, ≤6 candidate thumbnails (the
 * AI's words as alt / title), the AI's picks pre-ticked. The owner ticks exactly `pick_n`; the caller's "Send these"
 * posts them (canPick / buildPickPayload). Presentation only: ticks come from ultraRunReducer's `picked`.
 */
import { cn } from "@/lib/utils";
import type { StepStatus } from "./ultraRunReducer";

export function PickCard({ step, ticked, disabled, onTick }: {
  step: StepStatus;
  ticked: number[];
  disabled: boolean;
  onTick: (id: number) => void;
}) {
  const n = step.pick_n ?? 0;
  const ai = new Set(step.picks ?? []);
  return (
    <section data-pick-card={step.id} aria-label={`Pick ${n}`}
      className="rounded-[12px] bg-bg-elev-1 px-4 py-4 ring-1 ring-accent/60 sm:px-6">
      <h3 className="break-words text-[15px] font-medium text-fg">{step.question}</h3>
      <p className="mt-1 text-[13px] text-fg-dim" data-pick-count>
        {`Tick exactly ${n}: ${ticked.length} of ${n} ticked. The AI’s picks start ticked.`}
      </p>
      <ul className="mt-3 grid grid-cols-3 gap-2">
        {(step.candidates ?? []).map((c) => {
          const on = ticked.includes(c.id);
          const words = c.description || `${c.type ?? "media"} ${c.id}`;
          return (
            <li key={c.id} className="min-w-0">
              <label title={words}
                className={cn("relative block cursor-pointer overflow-hidden rounded-md bg-bg ring-2",
                  on ? "ring-accent" : "ring-transparent", disabled && "cursor-not-allowed opacity-60")}>
                <input type="checkbox" className="absolute left-1.5 top-1.5 z-10 size-4 accent-[var(--color-accent)]"
                  checked={on} disabled={disabled} onChange={() => onTick(c.id)}
                  aria-label={`${words}${ai.has(c.id) ? " (AI pick)" : ""}`} />
                {c.thumb
                  // eslint-disable-next-line @next/next/no-img-element -- a relay thumb path, like VaultTile
                  ? <img src={c.thumb} alt={words} className="aspect-square w-full object-cover" loading="lazy" />
                  :<span className="grid aspect-square w-full place-items-center text-[12px] text-fg-dim">{c.type ?? "media"}</span>}
                {ai.has(c.id) && (
                  <span className="absolute bottom-1 right-1 rounded bg-black/70 px-1 text-[11px] text-white">AI</span>
                )}
              </label>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
