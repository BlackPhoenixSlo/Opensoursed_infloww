"use client";

import { useEffect, useReducer, useRef } from "react";
import { useQuery } from "@tanstack/react-query";

import { TableSkeleton } from "@/components/ui/Skeleton";
import { IfModal, ifButtonClass } from "@/components/ui/infloww";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { relay, RelayError } from "@/lib/relay";

import { leakKeys } from "./leakKeys";
import { dayLabel, viewerZone } from "./leakView";
import { PopupOverlay } from "./PopupOverlayLayer";
import { SCENE_LABEL, type OfferVideo, type SceneKind, type Scenes } from "./popupOverlay";
import { PLAYER_START, playerReducer, playerView } from "./popupPlayer";
import { leadLine, type RemovalOffer } from "./removalOffer";

export type OfferRead = {
  offer: RemovalOffer;
  preview_leak: unknown;
  video: OfferVideo | null;
  scenes: Scenes;
  last_checked_at: string | null;
};

const PHONE = "(max-width: 639px)";
const REDUCED = "(prefers-reduced-motion: reduce)";

export const popupTitle = (brand: string) => `Start removal with ${brand}`;
export const contactLabel = (brand: string) => `Contact ${brand}`;

const part = (scopeAccountId: string | null, name: "video" | "poster" | "captions") =>
  `/admin/leaks/offer-video/${name}${scopeAccountId ? `?account_id=${encodeURIComponent(scopeAccountId)}` : ""}`;

function Player({ scopeAccountId, video, scenes, offer }: {
  scopeAccountId: string | null; video: OfferVideo | null; scenes: Scenes; offer: RemovalOffer;
}) {
  const [state, dispatch] = useReducer(playerReducer, PLAYER_START);
  const phone = useMediaQuery(PHONE);
  const reduced = useMediaQuery(REDUCED);
  const track = useRef<HTMLTrackElement>(null);
  const view = playerView(video, state);

  useEffect(() => {
    const el = track.current;
    if (!el) return;
    const fail = () => dispatch({ type: "captions_failed" });
    el.addEventListener("error", fail);
    return () => el.removeEventListener("error", fail);
  }, [view.player]);

  if (!view.player || !video) return null;
  const sync = (e: React.SyntheticEvent<HTMLVideoElement>) => dispatch({ type: "time", t: e.currentTarget.currentTime });
  return (
    <div data-section="video">
      <div className="relative overflow-hidden rounded-[8px] bg-black">
        <video
          className="block aspect-video w-full"
          src={part(scopeAccountId, "video")}
          poster={view.poster ? part(scopeAccountId, "poster") : undefined}
          playsInline
          preload="metadata"
          controls
          onError={() => dispatch({ type: "video_failed" })}
          onTimeUpdate={sync}
          onSeeked={sync}
        >
          <track ref={track} kind="captions" default src={part(scopeAccountId, "captions")} srcLang="en" label="English" />
        </video>
        {view.overlay && video.cues && !phone && (
          <PopupOverlay cues={video.cues} scenes={scenes} offer={offer} t={state.t} phone={false} reduced={reduced} />
        )}
      </div>
      {view.overlay && video.cues && phone && (
        <PopupOverlay cues={video.cues} scenes={scenes} offer={offer} t={state.t} phone reduced={reduced} />
      )}
    </div>
  );
}

function Results({ read }: { read: OfferRead }) {
  const now = new Date();
  const checked = read.last_checked_at && dayLabel(read.last_checked_at, now, viewerZone());
  const kinds = Object.keys(SCENE_LABEL) as SceneKind[];
  return (
    <section data-section="results" aria-label="Results" className="mt-4 rounded-[8px] border border-border p-4">
      <p className="text-[16px] font-medium text-fg">{leadLine(read.offer)}</p>
      <ul className="mt-2 flex flex-col gap-1 text-[13px] text-muted">
        {kinds.map((k) => (
          <li key={k}>
            {`${SCENE_LABEL[k]}: ${read.scenes[k].length}`}
            {read.scenes[k].length > 0 && ` · ${read.scenes[k].map((l) => `${l.leak_site} — ${l.title}`).join(" · ")}`}
          </li>
        ))}
      </ul>
      <p className="mt-2 text-[13px] text-muted">{checked ? `Last checked ${checked}` : "Not checked yet"}</p>
    </section>
  );
}

export function StartRemovalPopup({ creatorId, scopeAccountId, offer, onClose }: {
  creatorId: string;
  scopeAccountId: string | null;
  offer: RemovalOffer;
  onClose: () => void;
}) {
  const read = useQuery<OfferRead>({
    queryKey: leakKeys.offer(creatorId, scopeAccountId),
    queryFn: () => relay.get<OfferRead>(`/admin/leaks/watches/${creatorId}/offer`, { accountId: scopeAccountId }),
    gcTime: 0,
    staleTime: 0,
    retry: false,
  });
  const refused = read.error instanceof RelayError && read.error.status === 404;
  useEffect(() => {
    if (refused) onClose();
  }, [refused, onClose]);
  const shown = read.data?.offer ?? offer;
  const contact = (
    <a href={shown.contact_url} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer"
      className={ifButtonClass("primary")}>
      {contactLabel(shown.brand)}
    </a>
  );
  return (
    <IfModal title={popupTitle(shown.brand)} width={720} size="editor" onClose={onClose} footer={contact}>
      {read.data ? (
        <>
          <Player scopeAccountId={scopeAccountId} video={read.data.video} scenes={read.data.scenes} offer={read.data.offer} />
          <Results read={read.data} />
        </>
      ) : read.isPending ? (
        <TableSkeleton rows={3} />
      ) : (
        <p role="alert" className="text-[14px] text-muted">{"Couldn't load this Creator's results."}</p>
      )}
    </IfModal>
  );
}
