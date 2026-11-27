"use client";

import { Ban } from "lucide-react";

import { cn } from "@/lib/utils";

import { Pill } from "./LeakList";
import { activeScene, ILLUSTRATION, NO_LONGER, SCENE_LABEL, sceneView, type Cue, type SceneLeak, type Scenes } from "./popupOverlay";
import { leadLine, type RemovalOffer } from "./removalOffer";

function Removed({ leak }: { leak: SceneLeak }) {
  return (
    <div data-removed className="rounded-[6px] border border-border bg-black/40 px-3 py-2">
      <p className="flex items-center gap-1.5 truncate text-[12px] text-muted"><Ban className="h-3.5 w-3.5 shrink-0" />{leak.leak_site}</p>
      <p className="mt-0.5 text-[13px] text-fg">{NO_LONGER}</p>
      <p className="text-[11px] text-muted">{ILLUSTRATION}</p>
    </div>
  );
}

function Found({ leak, row }: { leak: SceneLeak; row: boolean }) {
  return (
    <div data-found className="rounded-[6px] border border-border bg-black/60 px-3 py-2">
      <p className="truncate text-[12px] text-muted">{leak.leak_site}</p>
      <p className={cn("text-[13px] text-fg", row ? "truncate" : "line-clamp-2")}>{leak.title}</p>
      {!row && <div className="mt-1"><Pill pill={leak.pill} /></div>}
    </div>
  );
}

export function PopupOverlay({ cues, scenes, offer, t, phone, reduced }: {
  cues: Cue[];
  scenes: Scenes;
  offer: RemovalOffer;
  t: number;
  phone: boolean;
  reduced: boolean;
}) {
  const scene = activeScene(cues, t);
  return (
    <div
      aria-hidden="true"
      data-overlay
      data-layout={phone ? "below" : "over"}
      data-scene={scene?.kind ?? "none"}
      className={cn("pointer-events-none text-fg",
        phone ? "mt-2" : "absolute inset-x-3 top-3 bottom-14 overflow-hidden")}
    >
      {scene && (
        <div key={scene.kind} className={cn("rounded-[8px] bg-black/50 p-3", !reduced && "animate-[fade-in_300ms_ease-out_backwards]")}>
          {scene.kind === "end" ? (
            <div data-end>
              <p className="text-[28px] font-semibold leading-none">{offer.n}</p>
              <p className="mt-1 text-[14px]">{leadLine(offer)}</p>
            </div>
          ) : (
            <SceneBody label={SCENE_LABEL[scene.kind]} leaks={scenes[scene.kind]} grid={scene.kind === "google_images"}
              row={scene.kind === "google"} t={t} start={scene.start} end={scene.end} />
          )}
        </div>
      )}
    </div>
  );
}

function SceneBody({ label, leaks, grid, row, t, start, end }: {
  label: string; leaks: SceneLeak[]; grid: boolean; row: boolean; t: number; start: number; end: number | null;
}) {
  const view = sceneView(leaks, t, start, end);
  return (
    <>
      <div className="mb-2 flex items-center justify-between gap-2">
        <p className="text-[13px] font-medium">{label}</p>
        {view.kind === "cards" && view.badge && (
          <span data-badge className="rounded-full bg-white/10 px-2 py-0.5 text-[11px]">{view.badge}</span>
        )}
      </div>
      {view.kind === "empty" ? (
        <p className="text-[13px] text-muted">{view.text}</p>
      ) : (
        <div className={cn("grid gap-2", grid ? "grid-cols-2 sm:grid-cols-3" : "grid-cols-1")}>
          {view.cards.map((leak) => view.flipped
            ? <Removed key={leak.leak_id} leak={leak} />
            : <Found key={leak.leak_id} leak={leak} row={row} />)}
        </div>
      )}
    </>
  );
}
