/**
 * The placeholder for the routes we have not rebuilt (the Fansly Manager
 * pages). It is Infloww's own pre-Start screen, `MultiWelcome`: the Fansly x
 * Infloww logo row, one line of copy and a Start button. Infloww opens
 * fansly.com in a BrowserView after Start; ours is disabled and says so.
 * Server-safe (no hooks), so route files can render it directly.
 */

import { notFound } from "next/navigation";
import { ArrowRight, X } from "lucide-react";

import { IfMark } from "@/components/auth/SiteLook";
import { PlatformLogo } from "@/components/shell/PlatformSwitcher";
import { findNavLink } from "@/lib/nav";
import { BRAND_NAME } from "@/lib/brand";

/** Infloww's `._content_kvaan_1`: centred column, gap 16, Home-B1 (`bg`). The
 *  ink is T0 (`nav-fg-active`: #fff dark, #000 light). */
function MultiWelcome({ title }: { title: string }) {
  return (
    <div className="flex h-full min-h-[calc(100dvh-var(--shell-top,56px))] flex-col items-center justify-center gap-4 bg-bg text-nav-fg-active">
      <h1 className="sr-only">{title}</h1>
      <div className="flex items-center gap-4" aria-hidden>
        <PlatformLogo platform="fansly" className="size-8" />
        <X className="size-6" />
        <IfMark className="size-8" />
        <span className="text-[22px] leading-none font-extrabold tracking-tight">{BRAND_NAME.toUpperCase()}</span>
      </div>
      <p className="text-base font-medium">Grow your revenue on Fansly with {BRAND_NAME}</p>
      <button
        type="button"
        disabled
        title="Not built yet: Infloww opens fansly.com here"
        className="inline-flex h-9 items-center gap-2 rounded-lg bg-[#fe7d50] px-4 text-base font-medium text-white disabled:cursor-not-allowed"
      >
        <ArrowRight className="size-5" strokeWidth={2.5} aria-hidden />
        Start
      </button>
      <p className="text-xs text-fg-dim">
        {title} is not built yet. Infloww shows fansly.com here after Start.
      </p>
    </div>
  );
}

/** A whole route that is only the placeholder. The title comes from the nav
 *  tree; an href the tree does not know (or one that is built) is a 404. */
export function NotBuiltYetRoute({ href }: { href: string }) {
  const link = findNavLink(href);
  if (!link?.notBuilt) notFound();
  return <MultiWelcome title={link.label} />;
}
