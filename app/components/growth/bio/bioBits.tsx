"use client";

/** Bits the bio pages screens share: the Mode names and help (v2 `profile.js:105-108`), the page avatar and a page
 *  address with Copy and Open. */
import { ExternalLink } from "lucide-react";

import { CopyButton } from "@/components/growth/_bits";
import type { BioMode } from "@/hooks/useBioPages";
import { cn } from "@/lib/utils";

export const MODE_NAMES: Record<BioMode, string> = { direct: "Direct", escape_ig: "Escape" };
export const MODE_HELP: Record<BioMode, string> = {
  direct: "Direct opens the Destination straight away.",
  escape_ig: "Escape shows Visitors in the Instagram or TikTok browser a screen that helps them into Safari or Chrome; "
    + "a Visitor already in a real browser never sees it.",
};

/** A round avatar from the page's image (a background, so no `<img>` sizing), else the name's first letter. */
export function PageAvatar({ url, name, size = 32, className }: { url: string; name: string; size?: number; className?: string }) {
  return (
    <span aria-hidden
      className={cn("grid shrink-0 place-items-center overflow-hidden rounded-full bg-bg-elev-2 bg-cover bg-center text-fg-dim", className)}
      style={{ width: size, height: size, fontSize: size * 0.42, backgroundImage: url ? `url("${url}")` : undefined }}>
      {url ? null : (name.trim()[0] ?? "?").toUpperCase()}
    </span>
  );
}

/** The page's address (or its path while this server has no public bio address), with Copy and Open when public. */
export function PageAddress({ url, path, className }: { url: string | null; path: string; className?: string }) {
  return (
    <div className={cn("flex min-w-0 flex-wrap items-center gap-x-1 gap-y-0.5", className)}>
      <span className={cn("min-w-0 truncate text-[13px]", url ? "text-accent" : "text-fg-dim")} title={url ?? path}>
        {url ?? path}
      </span>
      {url && (
        <span className="flex shrink-0 items-center">
          <CopyButton text={url} label="Copy" />
          <a href={url} target="_blank" rel="noreferrer" aria-label="Open the page"
            className="grid h-7 w-7 place-items-center rounded text-fg-dim hover:text-accent">
            <ExternalLink className="h-3.5 w-3.5" aria-hidden />
          </a>
        </span>
      )}
    </div>
  );
}
