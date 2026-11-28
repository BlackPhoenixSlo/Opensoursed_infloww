"use client";

import { useEffect, useReducer, useRef } from "react";
import { Link as LinkIcon } from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { IfButton } from "@/components/ui/infloww";
import { useSfw } from "@/hooks/useBlurMode";
import { cn } from "@/lib/utils";

import { leakKeys } from "./leakKeys";
import { KIND_ICON, Pill } from "./LeakList";
import {
  PREVIEW_FAILED, PREVIEW_LABEL, RETRY_MS, stripTiles, thumbSrc, TILE_START, tileReducer, tileView, type Tile,
} from "./leakPreview";
import { leakRead } from "./leakRead";
import { viewerZone, type LeakPage } from "./leakView";

function PreviewTile({ tile, sfwOn, scopeAccountId, onOpen, className }: {
  tile: Tile;
  sfwOn: boolean;
  scopeAccountId: string | null;
  onOpen?: (accountId: string) => void;
  className?: string;
}) {
  const [state, dispatch] = useReducer(tileReducer, TILE_START);
  const button = useRef<HTMLButtonElement>(null);
  const link = useRef<HTMLAnchorElement>(null);
  const waiting = state.phase === "waiting";
  useEffect(() => {
    if (!waiting) return;
    const t = setTimeout(() => dispatch({ type: "retry" }), RETRY_MS);
    return () => clearTimeout(t);
  }, [waiting]);
  const view = tileView(state, sfwOn, tile.thumb);
  const Icon = KIND_ICON[tile.kind] ?? LinkIcon;
  const onError = () => {
    if (state.phase === "retry" && document.activeElement === button.current) link.current?.focus();
    dispatch({ type: "error" });
  };
  return (
    <li data-tile={tile.leakId} aria-label={`${tile.title} · ${PREVIEW_LABEL}`}
      className={cn("flex min-w-0 flex-col gap-1 rounded-[4px] border border-border bg-bg-elev-1 p-2 text-[14px]", className)}>
      {view.image ? (
        <button ref={button} type="button" aria-pressed={view.pressed} aria-label={`${view.label}: ${tile.title}`}
          onClick={() => dispatch({ type: "toggle" })} className="block aspect-[4/3] w-full overflow-hidden rounded-[4px] bg-bg-elev-2">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img key={view.attempt} src={thumbSrc(tile, scopeAccountId)} alt="Google preview" loading="lazy" onError={onError}
            className={cn("h-full w-full object-cover", view.blurred && "blur-md", view.hidden && "invisible")} />
        </button>
      ) : (
        <div data-thumb="placeholder" className="flex aspect-[4/3] w-full items-center justify-center rounded-[4px] bg-bg-elev-2 text-muted">
          {view.failed ? <span className="text-[13px]">{PREVIEW_FAILED}</span> : <Icon aria-hidden="true" className="h-6 w-6" />}
        </div>
      )}
      <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
        {tile.creator && onOpen && (
          <IfButton variant="link" className="h-auto" onClick={() => onOpen(tile.accountId)}>{tile.creator}</IfButton>
        )}
        <Pill pill={tile.pill} />
      </div>
      <a ref={link} href={tile.url} target="_blank" rel="noreferrer noopener" className="flex min-w-0 flex-col break-all">
        <span className="text-muted">{tile.site}</span>
        <span className="text-accent hover:text-accent-hover">{tile.title}</span>
      </a>
      <span className="text-[13px] text-muted">{tile.seen}</span>
      <span className="text-[12px] text-muted">{PREVIEW_LABEL}</span>
    </li>
  );
}

export function PreviewGrid({ label, tiles, scopeAccountId }: { label: string; tiles: Tile[]; scopeAccountId: string | null }) {
  const [sfwOn] = useSfw();
  return (
    <ul key={`${scopeAccountId ?? "all"}:${sfwOn}`} aria-label={label} className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {tiles.map((t) => <PreviewTile key={t.key} tile={t} sfwOn={sfwOn} scopeAccountId={scopeAccountId} />)}
    </ul>
  );
}

export function PreviewStrip({ accountId, names, onOpen }: {
  accountId: string | null;
  names: Record<string, string>;
  onOpen: (accountId: string) => void;
}) {
  const qc = useQueryClient();
  const [sfwOn] = useSfw();
  const strip = useQuery({
    queryKey: leakKeys.strip(accountId),
    queryFn: () => leakRead<LeakPage>(qc, "/admin/leaks/all?preview=1", accountId),
  });
  const tiles = stripTiles(strip.data?.leaks ?? [], names, new Date(), viewerZone());
  if (!tiles.length) return null;
  return (
    <section aria-label="Seen in Google Images" className="mb-4">
      <h2 className="mb-2 text-[16px] font-medium text-fg">Seen in Google Images</h2>
      <ul key={`${accountId ?? "all"}:all:${sfwOn}`} className="flex gap-3 overflow-x-auto pb-1">
        {tiles.map((t) => (
          <PreviewTile key={t.key} tile={t} onOpen={onOpen} className="w-[220px] shrink-0"
            sfwOn={sfwOn} scopeAccountId={accountId} />
        ))}
      </ul>
    </section>
  );
}
