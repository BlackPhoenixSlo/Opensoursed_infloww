"use client";

/**
 * /group — group-chat tab. Up to 8 individual fan conversations rendered
 * side-by-side for fast multi-chat across accounts/models.
 *
 * Not a real group thread (OF has no such concept) — just stacked panes,
 * each posting to its own one-on-one chat.
 *
 * Per-tab identity: each /group tab generates a tabId (persisted in
 * sessionStorage so a refresh keeps it) and publishes its current state
 * under `chatterly:group-tab:<tabId>` in localStorage with a heartbeat.
 * Source tabs scan all live registries to route adds — clicking 👥 group
 * on a fan already in some tab focuses that specific tab; otherwise the
 * fan goes into the freshest tab with room; if all live tabs are full,
 * a fresh group tab is spawned. Net effect: no accidental duplicates of
 * the same fan across multiple group tabs. A duplicate that still happens
 * (a 👥 click while the tab holding the fan reloads) converges: older wins,
 * the younger tab drops the fan at mount or on its next heartbeat. A tab
 * whose heartbeat went stale (throttled / frozen past the TTL, then woken or
 * reloaded) comes back as the youngest, so a fan routed around it meanwhile
 * stays where he went.
 *
 * BroadcastChannel messages carry the target tabId so only the addressed
 * tab acts on add/focus.
 */

import { useEffect, useReducer, useRef, useState } from "react";
import Link from "next/link";
import { useQueries, useQueryClient } from "@tanstack/react-query";

import { FanList } from "@/components/chat/FanList";
import { GroupPane } from "@/components/group/GroupPane";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { useIsDesktop } from "@/hooks/useIsDesktop";
import { useInboxRealtime } from "@/hooks/useInboxRealtime";
import { cachedOFUserQuery } from "@/hooks/useOFUser";
import { cn } from "@/lib/utils";
import { proxyImage } from "@/lib/mediaUrl";
import { onPopoutClick } from "@/lib/nav";
import {
  GROUP_CHANNEL_NAME,
  GROUP_HEARTBEAT_MS,
  GROUP_HEARTBEAT_TTL_MS,
  GROUP_REPLACE_EVENT,
  GROUP_SLOT_CAP,
  GROUP_WINDOW_NAME,
  cleanGroupMessage,
  listOf,
  readAllLiveGroupTabs,
  removeGroupTabRegistry,
  writeGroupTabRegistry,
} from "@/lib/groupChannel";
import { BRAND_NAME } from "@/lib/brand";
import { initialSlotsState, keptSlots, slotsReducer } from "./slotsReducer";
import {
  countUnresponded, isStaleReload, olderTabs, readLastBeat, readSlots, resolveCreatedAt, resolveTabId, takeSeedParams,
  writeLastBeat, writeSlots,
} from "./groupTabStorage";

export default function GroupChatPage() {
  // Keep SSE patches landing in the right query caches — same hook the
  // inbox page mounts. Without it the panes only pick up new messages
  // via the 30s poll.
  useInboxRealtime();

  // Hydration-gated: SSR renders nothing, the post-mount effect seeds
  // from sessionStorage + ?add=. Avoids a flicker of empty grid. Every
  // write to the slots, the shown pane and the owed add-acks is an action
  // of slotsReducer.
  const [state, dispatch] = useReducer(slotsReducer, initialSlotsState);
  const { hydrated, slots, active, acks } = state;
  const tabIdRef = useRef<string>("");
  const createdAtRef = useRef<number>(0);
  const spawnTokenRef = useRef<string | null>(null);
  const lastTickAtRef = useRef<number>(0);
  const channelRef = useRef<BroadcastChannel | null>(null);

  useEffect(() => {
    const { seeds, spawnToken, fresh } = takeSeedParams();
    // A reload keeps the tab's id and age (sessionStorage), so the older-wins
    // reconcile still treats it as the older tab; a fresh tab gets new ones.
    // A reload past the TTL since its last beat is reborn young, as a stale
    // tick is (below): the first tick after mount cannot see that gap.
    tabIdRef.current = resolveTabId(fresh);
    createdAtRef.current = resolveCreatedAt(fresh || isStaleReload(readLastBeat(), Date.now()));
    spawnTokenRef.current = spawnToken;
    // ?add= / ?slots= is the marker that this is a FRESHLY-OPENED group
    // tab (someone clicked 👥 group on a chat, or "open last 8" on the
    // money rail — the cold path or the overflow path). In every case
    // the new tab should start clean with just the requested fans, even
    // though some browsers copy sessionStorage to a window.open'd child
    // (which would otherwise carry over the previous group session).
    //
    // Neither param means this is a reload of the SAME tab (or someone
    // typed /group manually) — restore the slot list from
    // sessionStorage so refresh keeps the layout.
    const initial = seeds.length > 0 ? seeds : readSlots();
    // StrictMode (dev) runs this effect twice, and the second run finds the
    // seed params already stripped from the URL: store the seeds now so it
    // reads them back. The persist effect stores the reconciled list next.
    writeSlots(initial);
    // Reconcile-on-mount: drop slots that an OLDER live tab already
    // holds. Handles the residual case where two source tabs raced
    // to spawn and we both ended up with the same fan. Older wins (and
    // the heartbeat below keeps applying it once both are live).
    const older = olderTabs(readAllLiveGroupTabs(), { tabId: tabIdRef.current, createdAt: createdAtRef.current });
    dispatch({ type: "hydrate", slots: initial, heldElsewhere: older });
  }, []);

  // Persist on every change so a refresh keeps the layout.
  useEffect(() => {
    if (!hydrated) return;
    writeSlots(slots);
  }, [slots, hydrated]);

  // Same-tab re-seed. The money rail lives in the root layout, so it also
  // renders HERE — and a BroadcastChannel never delivers to its own sender,
  // so clicking "open last 8" inside the group tab reaches us as a DOM
  // event instead of a `replace` message.
  useEffect(() => {
    const onReplace = (e: Event) => {
      dispatch({ type: "replace", slots: listOf((e as CustomEvent<{ slots?: unknown } | null>).detail?.slots) });
    };
    window.addEventListener(GROUP_REPLACE_EVENT, onReplace);
    return () => window.removeEventListener(GROUP_REPLACE_EVENT, onReplace);
  }, []);

  // Tab lifetime: window.name stamp, the BroadcastChannel listener and the
  // registry teardown. Keyed on `hydrated` only — a slot change must not
  // close and reopen the channel (a message sent in between would be lost).
  useEffect(() => {
    if (!hydrated) return;
    // Stamp window.name so a same-BCG window.open(..., GROUP_WINDOW_NAME)
    // call can find this tab. Cross-BCG it doesn't — focus relies on
    // the broadcast path for those cases. Cleared on unmount so a
    // client-side navigation away from /group doesn't leave the stamp
    // behind — `openGroupTab` keys off window.name as a re-entry guard
    // and would otherwise no-op every 👥 click on the next page. Don't
    // try to restore a prior value: window.name persists across refresh,
    // so the "prior" value is often this same stamp from a past mount.
    try { window.name = GROUP_WINDOW_NAME; } catch { /* sealed in some iframes */ }
    const tabId = tabIdRef.current;
    if (!tabId) return;

    let channel: BroadcastChannel | null = null;
    try {
      channel = new BroadcastChannel(GROUP_CHANNEL_NAME);
      channelRef.current = channel;
      // Announce ourselves so the source that spawned us can pair its
      // held Window ref with our tabId. No-op for the source(s) that
      // didn't spawn us (they ignore claims for tokens they don't hold).
      if (spawnTokenRef.current) {
        try { channel.postMessage({ type: "claim", tabId, spawnToken: spawnTokenRef.current }); } catch {}
      }
      // Any same-origin page can post here: cleanGroupMessage checks the
      // envelope; slotsReducer still decides each slot (and its ack).
      channel.onmessage = (e: MessageEvent<unknown>) => {
        const msg = cleanGroupMessage(e.data);
        if (!msg) return;
        // Address filter: ignore messages not meant for THIS tab.
        // Multiple group tabs are alive simultaneously and each scopes
        // its actions to its own tabId.
        if (msg.type !== "add" && msg.type !== "focus" && msg.type !== "replace") return;
        if (msg.tabId !== tabId) return;
        // add / replace: the reducer decides the ack against the state it
        // applies the message to and queues it; the ack effect posts it.
        // The source spawns an overflow tab on ok:false.
        if (msg.type === "replace") {
          dispatch({ type: "replace", slots: msg.slots, reqId: msg.reqId });
        }
        if (msg.type === "add") {
          dispatch({ type: "add", slot: { accountId: msg.accountId, fanId: msg.fanId }, reqId: msg.reqId });
        }
        // For every addressed message: try to bring this tab forward.
        // Browsers vary on whether window.focus() from a
        // BroadcastChannel handler is honored. When it works the click
        // on the source tab feels like "switched to group". When
        // denied, slot still landed; user alt-tabs manually.
        try { window.focus(); } catch { /* policy denial — ignore */ }
      };
    } catch {
      /* No BroadcastChannel — gracefully degrade. The source tab's
         fallback path (window.open with ?add=) still works. */
    }

    // pagehide is the reliable cross-browser teardown signal (fires on
    // bfcache eviction and iOS where beforeunload is unreliable).
    const onPagehide = () => { removeGroupTabRegistry(tabId); };
    window.addEventListener("pagehide", onPagehide);

    return () => {
      window.removeEventListener("pagehide", onPagehide);
      removeGroupTabRegistry(tabId);
      channelRef.current = null;
      if (channel) { try { channel.close(); } catch {} }
      try { if (window.name === GROUP_WINDOW_NAME) window.name = ""; } catch {}
    };
  }, [hydrated]);

  // Post the add-acks the reducer queued, then drain exactly those.
  useEffect(() => {
    if (acks.length === 0) return;
    const tabId = tabIdRef.current;
    for (const a of acks) {
      try { channelRef.current?.postMessage({ type: "add-ack", tabId, reqId: a.reqId, ok: a.ok }); } catch {}
    }
    dispatch({ type: "acksSent", reqIds: acks.map((a) => a.reqId) });
  }, [acks]);

  // Heartbeat: write this tab's registry entry now (so source tabs see a
  // slot change at once) and every GROUP_HEARTBEAT_MS. The registry is
  // keyed by this tab's id, so multiple group tabs each have their own
  // entry — scanners see all of them. Every beat is one reconcile: drop the
  // fans an OLDER live tab holds (the mount rule, kept while both live) and
  // advertise only the rest, so a fan we yield never makes his holder drop
  // him too. A tab that reloads keeps its age, so when a younger tab took one
  // of its fans meanwhile, the younger one gives him up.
  //
  // Stale tab: a gap since our last beat longer than the registry TTL (a
  // hidden tab throttled to ~1 timer/min, a frozen one) means scanners saw
  // us dead and may have put our fans in another tab, acked ok. Such a tab
  // is reborn young (createdAt = now, persisted): every live tab is older,
  // so it gives up whatever any of them holds, now and if a racing add lands
  // there just after this read. The interval and visibilitychange run the
  // same tick, so whichever fires first sees the gap. Never on the first
  // tick after mount: a reload keeps its age, or was already reborn at mount
  // when its stored last beat was stale (above), and StrictMode's re-run
  // follows a beat.
  useEffect(() => {
    if (!hydrated) return;
    const tabId = tabIdRef.current;
    if (!tabId) return;
    const tick = () => {
      const now = Date.now();
      if (lastTickAtRef.current > 0 && now - lastTickAtRef.current > GROUP_HEARTBEAT_TTL_MS) {
        createdAtRef.current = resolveCreatedAt(true, now);
      }
      const older = olderTabs(readAllLiveGroupTabs(), { tabId, createdAt: createdAtRef.current });
      if (older.length > 0) dispatch({ type: "dropHeldBy", others: older });
      writeGroupTabRegistry(tabId, createdAtRef.current, keptSlots(slots, older));
      writeLastBeat(now);
      lastTickAtRef.current = now;
    };
    const onVisibility = () => { if (document.visibilityState === "visible") tick(); };
    tick();
    const interval = window.setInterval(tick, GROUP_HEARTBEAT_MS);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [hydrated, slots]);

  // Unresponded count among loaded panes: derived from whatever chats
  // data is already in the React Query cache (no extra fetches). SSE
  // keeps lastMessage current; the cache subscription re-counts whenever
  // any ["chats", ...] entry changes, and the page re-renders only when the
  // count does: a render per live message re-rendered the Fan List and
  // every pane with it.
  const qc = useQueryClient();
  const [unrespondedCount, setUnrespondedCount] = useState(0);
  useEffect(() => {
    let live = true;
    let queued = false;
    const recount = () => setUnrespondedCount(countUnresponded(qc, slots));
    recount();
    // Only react to actual data updates. observerAdded/Removed events
    // fire on every render of subscribers (e.g. FanList mounted below).
    // One recount per microtask: a batch frame's writes count once.
    const unsub = qc.getQueryCache().subscribe((e) => {
      if (e?.type !== "updated" || queued) return;
      const k = e?.query?.queryKey as readonly unknown[] | undefined;
      if (!k || k[0] !== "chats") return;
      queued = true;
      queueMicrotask(() => {
        queued = false;
        if (live) recount();
      });
    });
    return () => { live = false; unsub(); };
  }, [qc, slots]);

  const groupTabTitle = unrespondedCount > 0
    ? `(${unrespondedCount}) Group chat · ${BRAND_NAME}`
    : `Group chat · ${BRAND_NAME}`;
  useDocumentTitle(groupTabTitle);

  const full = slots.length >= GROUP_SLOT_CAP;
  // One layout mounted, not both with CSS hiding the other: a hidden Fan List
  // and a hidden copy of the active pane still render on every live message
  // (twice the rows, measured 614 vs 307 under a DM flood).
  const desktop = useIsDesktop();
  // Responsive grid (md+): panes shrink as count grows. Tailwind picks
  // the narrowest column that still fits ~280px content. At 8 panes on
  // a 1440 monitor that lands at ~250px each — tight but legible. Mobile
  // (< md) doesn't use the grid at all — see the tab strip below.
  const gridCols =
    slots.length <= 1
      ? "grid-cols-1"
      : slots.length === 2
        ? "grid-cols-2"
        : slots.length <= 4
          ? "grid-cols-2"
          : "grid-cols-2 lg:grid-cols-3 xl:grid-cols-4";

  // Mobile renders one pane at a time, switched via a horizontal tab
  // strip. Reason: 8 simultaneous `useChatMessages` + SSE subscriptions
  // on a phone is brutal — at 360px wide there's no parallel-visibility
  // win to justify the CPU. Tabs let only the active pane stay hot;
  // others unmount via the React key=, freeing their hooks. `active` is
  // the reducer's: an added fan is shown, a removed one hands over to
  // whoever takes its place.
  const shown = slots[active];

  // Observe-only cache reads for tab labels — FanList's enrichWithUsers
  // has already populated `["of-user", aid, fid]` for any slot that came
  // from the rail.
  const slotProfiles = useQueries({
    queries: slots.map((s) => cachedOFUserQuery(s.accountId, s.fanId)),
  });
  const tabLabel = (i: number): string => {
    const s = slots[i];
    if (!s) return "";
    const p = slotProfiles[i]?.data;
    return p?.customNickname || p?.name || p?.username || `fan ${s.fanId}`;
  };

  return (
    <div className="h-chat flex flex-col lg:grid lg:grid-cols-[300px_minmax(0,1fr)] overflow-hidden">
      {/* On mobile, the inbox rail collapses behind a toggle so the
       *  panes have room. Tap the bar to slide it open/closed.
       *  `shrink-0` keeps the summary visible even when the panes
       *  wrapper below claims remaining space via `flex-1`. */}
      {!desktop && <details className="lg:hidden shrink-0 border-b border-border bg-panel group">
        <summary className="px-3 py-2 text-xs font-semibold cursor-pointer flex items-center justify-between gap-2 list-none [&::-webkit-details-marker]:hidden">
          <span className="flex items-center gap-1.5">
            <span className="text-fg-dim group-open:rotate-90 transition-transform inline-block">›</span>
            <span>Group chat</span>
            {unrespondedCount > 0 && (
              <span
                className="px-1.5 rounded-full bg-warn/20 text-warn text-[10px] font-medium leading-[16px]"
                title="Loaded panes where the fan sent the last message"
              >
                {unrespondedCount} unresponded
              </span>
            )}
          </span>
          <span className="text-[10px] text-fg-dim shrink-0">
            {slots.length} / {GROUP_SLOT_CAP}
          </span>
        </summary>
        <div className="border-t border-border h-[60vh] flex flex-col">
          <div className="px-3 py-2 border-b border-border text-[11px] text-fg-dim flex items-center justify-between gap-2">
            <Link href="/messages-pro" onClick={(e) => onPopoutClick(e, "/messages-pro")} className="hover:text-fg underline underline-offset-2">
              ← inbox
            </Link>
            {full && <span className="text-warn">full — close one to add</span>}
          </div>
          {/* The Fan List draws no edge of its own; this pane keeps its right border. */}
          <div className="flex-1 min-h-0 overflow-hidden border-r border-border">
            <FanList
              selected={null}
              onSelect={(sel) => dispatch({ type: "add", slot: { accountId: sel.accountId, fanId: sel.fanId } })}
              setTabTitle={false}
            />
          </div>
        </div>
      </details>}

      {desktop && <div className="hidden lg:flex flex-col min-h-0 border-r border-border bg-panel">
        <div className="px-3 py-2 border-b border-border flex items-center justify-between gap-2">
          <div className="text-xs font-semibold flex items-center gap-1.5">
            <span>Group chat</span>
            {unrespondedCount > 0 && (
              <span
                className="px-1.5 rounded-full bg-warn/20 text-warn text-[10px] font-medium leading-[16px]"
                title="Loaded panes where the fan sent the last message"
              >
                {unrespondedCount} unresponded
              </span>
            )}
          </div>
          <div className="text-[10px] text-fg-dim shrink-0">
            {slots.length} / {GROUP_SLOT_CAP}
          </div>
        </div>
        <div className="px-3 py-2 border-b border-border text-[11px] text-fg-dim flex items-center justify-between gap-2">
          <Link href="/messages-pro" onClick={(e) => onPopoutClick(e, "/messages-pro")} className="hover:text-fg underline underline-offset-2">
            ← inbox
          </Link>
          {full && <span className="text-warn">full — close one to add</span>}
        </div>
        <div className="flex-1 min-h-0 overflow-hidden border-r border-border">
          <FanList
            selected={null}
            onSelect={(sel) => dispatch({ type: "add", slot: { accountId: sel.accountId, fanId: sel.fanId } })}
            setTabTitle={false}
          />
        </div>
      </div>}

      {/* `flex-1 min-h-0` claims the remaining vertical space on mobile
       *  (the outer is `flex flex-col` below md). On md+ the outer is a
       *  grid and `flex-1` is inert — the grid template owns layout. */}
      <div className="flex-1 min-h-0 overflow-hidden flex flex-col">
        {/* Mobile slot tabs — horizontal scrollable strip, one chip per
         *  slot. Active chip highlights, tap to switch the active pane
         *  below. Hidden on md+ (the desktop grid shows all panes). */}
        {hydrated && slots.length > 0 && (
          <nav className="lg:hidden flex overflow-x-auto no-scrollbar border-b border-border bg-panel shrink-0">
            {slots.map((s, i) => (
              <button
                key={`${s.accountId}:${s.fanId}`}
                type="button"
                onClick={() => dispatch({ type: "select", index: i })}
                className={cn(
                  "px-3 py-2 text-xs whitespace-nowrap border-r border-border shrink-0 max-w-[140px] truncate",
                  i === active
                    ? "bg-bg text-fg font-medium"
                    : "text-fg-dim hover:text-fg",
                )}
                title={tabLabel(i)}
              >
                {tabLabel(i)}
              </button>
            ))}
          </nav>
        )}

        <div className="flex-1 min-h-0 overflow-hidden">
          {!hydrated ? (
            <div className="grid place-items-center h-full text-sm text-fg-dim">…</div>
          ) : slots.length === 0 ? (
            <div className="grid place-items-center h-full p-8 text-center">
              <div className="max-w-sm space-y-2">
                <div className="text-sm font-medium">No chats in this group yet.</div>
                <p className="text-xs text-fg-dim">
                  Click any conversation in the left rail to add it. Up to {GROUP_SLOT_CAP}
                  {" "}panes side-by-side; refresh keeps them — close the tab to clear.
                </p>
              </div>
            </div>
          ) : (
            <>
              {/* Mobile: only the active slot is mounted. Switching tabs
               *  remounts via React key=, which also tears down the
               *  inactive pane's useChatMessages + SSE merge. */}
              {!desktop && <div className="lg:hidden h-full">
                {shown && (
                  <GroupPane
                    key={`m:${shown.accountId}:${shown.fanId}`}
                    accountId={shown.accountId}
                    fanId={shown.fanId}
                    onClose={() => dispatch({ type: "remove", slot: shown })}
                  />
                )}
              </div>}
              {/* Desktop: all panes in a responsive grid. */}
              {desktop && <div className={`hidden lg:grid ${gridCols} gap-2 p-2 h-full overflow-auto`}>
                {slots.map((s) => (
                  <GroupPane
                    key={`${s.accountId}:${s.fanId}`}
                    accountId={s.accountId}
                    fanId={s.fanId}
                    onClose={() => dispatch({ type: "remove", slot: s })}
                  />
                ))}
              </div>}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
