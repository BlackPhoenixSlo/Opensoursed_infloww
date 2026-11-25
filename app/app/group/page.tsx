"use client";


import { useEffect, useReducer, useRef, useState } from "react";
import Link from "next/link";
import { useQueries, useQueryClient } from "@tanstack/react-query";

import { FanList } from "@/components/chat/FanList";
import { GroupPane } from "@/components/group/GroupPane";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { useIsDesktop } from "@/hooks/useIsDesktop";
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
  const [state, dispatch] = useReducer(slotsReducer, initialSlotsState);
  const { hydrated, slots, active, acks } = state;
  const tabIdRef = useRef<string>("");
  const createdAtRef = useRef<number>(0);
  const spawnTokenRef = useRef<string | null>(null);
  const lastTickAtRef = useRef<number>(0);
  const channelRef = useRef<BroadcastChannel | null>(null);

  useEffect(() => {
    const { seeds, spawnToken, fresh } = takeSeedParams();
    tabIdRef.current = resolveTabId(fresh);
    createdAtRef.current = resolveCreatedAt(fresh || isStaleReload(readLastBeat(), Date.now()));
    spawnTokenRef.current = spawnToken;
    const initial = seeds.length > 0 ? seeds : readSlots();
    writeSlots(initial);
    const older = olderTabs(readAllLiveGroupTabs(), { tabId: tabIdRef.current, createdAt: createdAtRef.current });
    dispatch({ type: "hydrate", slots: initial, heldElsewhere: older });
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    writeSlots(slots);
  }, [slots, hydrated]);

  useEffect(() => {
    const onReplace = (e: Event) => {
      dispatch({ type: "replace", slots: listOf((e as CustomEvent<{ slots?: unknown } | null>).detail?.slots) });
    };
    window.addEventListener(GROUP_REPLACE_EVENT, onReplace);
    return () => window.removeEventListener(GROUP_REPLACE_EVENT, onReplace);
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    // Cleared on unmount: openGroupTab keys off window.name and would no-op every group click after navigating away. Don't restore a prior value; window.name survives refresh.
    try { window.name = GROUP_WINDOW_NAME; } catch { /* sealed in some iframes */ }
    const tabId = tabIdRef.current;
    if (!tabId) return;

    let channel: BroadcastChannel | null = null;
    try {
      channel = new BroadcastChannel(GROUP_CHANNEL_NAME);
      channelRef.current = channel;
      if (spawnTokenRef.current) {
        try { channel.postMessage({ type: "claim", tabId, spawnToken: spawnTokenRef.current }); } catch {}
      }
      channel.onmessage = (e: MessageEvent<unknown>) => {
        const msg = cleanGroupMessage(e.data);
        if (!msg) return;
        if (msg.type !== "add" && msg.type !== "focus" && msg.type !== "replace") return;
        if (msg.tabId !== tabId) return;
        if (msg.type === "replace") {
          dispatch({ type: "replace", slots: msg.slots, reqId: msg.reqId });
        }
        if (msg.type === "add") {
          dispatch({ type: "add", slot: { accountId: msg.accountId, fanId: msg.fanId }, reqId: msg.reqId });
        }
        try { window.focus(); } catch { /* policy denial */ }
      };
    } catch {
    }

    const onPagehide = () => { removeGroupTabRegistry(tabId); };
    // pagehide, not beforeunload: fires on bfcache eviction and iOS.
    window.addEventListener("pagehide", onPagehide);

    return () => {
      window.removeEventListener("pagehide", onPagehide);
      removeGroupTabRegistry(tabId);
      channelRef.current = null;
      if (channel) { try { channel.close(); } catch {} }
      try { if (window.name === GROUP_WINDOW_NAME) window.name = ""; } catch {}
    };
  }, [hydrated]);

  useEffect(() => {
    if (acks.length === 0) return;
    const tabId = tabIdRef.current;
    for (const a of acks) {
      try { channelRef.current?.postMessage({ type: "add-ack", tabId, reqId: a.reqId, ok: a.ok }); } catch {}
    }
    dispatch({ type: "acksSent", reqIds: acks.map((a) => a.reqId) });
  }, [acks]);

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

  const qc = useQueryClient();
  const [unrespondedCount, setUnrespondedCount] = useState(0);
  useEffect(() => {
    let live = true;
    let queued = false;
    const recount = () => setUnrespondedCount(countUnresponded(qc, slots));
    recount();
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
  const desktop = useIsDesktop();
  const gridCols =
    slots.length <= 1
      ? "grid-cols-1"
      : slots.length === 2
        ? "grid-cols-2"
        : slots.length <= 4
          ? "grid-cols-2"
          : "grid-cols-2 lg:grid-cols-3 xl:grid-cols-4";

  const shown = slots[active];

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

      <div className="flex-1 min-h-0 overflow-hidden flex flex-col">
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
              {!desktop && <div className="lg:hidden h-full">
                {/* Mobile mounts one pane: 8 useChatMessages + SSE subscriptions on a phone is too heavy. */}
                {shown && (
                  <GroupPane
                    key={`m:${shown.accountId}:${shown.fanId}`}
                    accountId={shown.accountId}
                    fanId={shown.fanId}
                    onClose={() => dispatch({ type: "remove", slot: shown })}
                  />
                )}
              </div>}
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
