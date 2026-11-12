import type { Metadata } from "next";
import Link from "next/link";
import { Sparkles } from "lucide-react";

import { PageFrame } from "@/components/shell/PageFrame";

export const metadata: Metadata = { title: "Full AI Chatter" };

/** The AI pages that run today (nav.ts labels). */
const LIVE = [
  { label: "Auto-reply", href: "/growth/auto-reply" },
  { label: "Get to know fans", href: "/growth/get-to-know-fans" },
  { label: "Auto Funnel", href: "/growth/auto-funnel" },
];

// Full AI Chatter (ours, nav.ts): a coming-soon page for the fully autonomous chatter. Owner-only in the sidebar.
export default function Page() {
  return (
    <PageFrame title="Full AI Chatter">
      <section className="flex min-h-[calc(100dvh-160px)] items-center justify-center">
        <div className="relative w-full max-w-[520px] overflow-hidden rounded-2xl border border-border bg-panel px-6 py-12 text-center max-sm:px-5 max-sm:py-10">
          <div aria-hidden className="pointer-events-none absolute -top-24 left-1/2 h-48 w-72 -translate-x-1/2 rounded-full bg-accent/25 blur-3xl" />
          <div className="relative mx-auto mb-6 flex size-16 items-center justify-center rounded-2xl bg-gradient-to-br from-accent to-pink shadow-lg shadow-accent/30">
            <Sparkles className="size-8 text-white" strokeWidth={1.75} />
          </div>
          <span className="relative mb-4 inline-block rounded-full border border-accent/40 bg-accent/10 px-3 py-1 text-[12px] font-medium tracking-wide text-accent uppercase">
            Coming soon
          </span>
          <h2 className="relative mb-3 text-[24px] leading-tight font-semibold text-balance text-fg max-sm:text-[22px]">
            Your chats, run end to end by AI
          </h2>
          <p className="relative mx-auto max-w-[400px] text-[15px] leading-relaxed text-fg-dim">
            A fully autonomous AI chatter that greets, warms up and sells to every fan on its own, around the clock.
          </p>
          <p className="relative mt-8 text-[13px] text-muted">
            Until then, the live AI lanes:{" "}
            {LIVE.map(({ label, href }, i) => (
              <span key={href}>
                {i > 0 && (i === LIVE.length - 1 ? " and " : ", ")}
                <Link href={href} className="text-link hover:underline">{label}</Link>
              </span>
            ))}
            .
          </p>
        </div>
      </section>
    </PageFrame>
  );
}
