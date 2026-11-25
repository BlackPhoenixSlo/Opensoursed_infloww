"use client";

import { useMemo, useState } from "react";

import { useActiveAccounts } from "@/hooks/useAccounts";
import { useOnScreenLease } from "@/hooks/useViewLease";
import { cn } from "@/lib/utils";
import { GROUP_SLOT_CAP, openGroupTabWithSlots, type GroupSlot } from "@/lib/groupChannel";
import type { RailSettings, Surface } from "@/lib/moneyRailStorage";
import { Row } from "./MoneyRailRow";
import { SettingsPanel } from "./MoneyRailSettings";
import { ROW_H, useRailDock } from "./useRailDock";
import { distinctPayers, payerIdOf, useMoneyRailFeed } from "./useMoneyRailFeed";

const HEADER_H = 38;
const SETTINGS_H = 280;
const VIEWPORT_MARGIN = 12;
const DEFAULT_EDGE_GAP = 12;

export function MoneyRailPanel({
  surface,
  settings,
  onSettingsChange,
}: {
  surface: Surface;
  settings: RailSettings;
  onSettingsChange: (next: RailSettings) => void;
}) {
  const activeAccounts = useActiveAccounts();
  const [settingsOpen, setSettingsOpen] = useState(false);

  const { dock, mounted, viewportH, panelRef, swallowClick, onHeaderPointerDown, toggle } = useRailDock(surface);
  const open = dock.open;
  const {
    targetAccountIds, merged, unseen, replyStates, placeholderAids, anyRefreshing, anyLoading,
  } = useMoneyRailFeed({ settings, activeAccounts, open });
  const track = useOnScreenLease("rail");

  const groupSlots = useMemo<GroupSlot[]>(() => distinctPayers(merged, GROUP_SLOT_CAP), [merged]);

  const showAccountTag = targetAccountIds.length > 1;
  const accountLabel = useMemo(() => {
    const m = new Map<string, string>();
    for (const a of activeAccounts) m.set(a.id, a.nickname || a.id);
    return m;
  }, [activeAccounts]);

  if (!mounted || targetAccountIds.length === 0) return null;

  const placed = dock.x != null && dock.y != null;

  // chrome height is estimated: measuring needs a post-render pass feeding back into the height it caused
  const chromeH = HEADER_H + (settingsOpen ? SETTINGS_H : 0);
  const onMessagesPro = surface === "inbox" || surface === "popup";
  const edgeGap = placed ? dock.y! : onMessagesPro ? 0 : DEFAULT_EDGE_GAP;
  const room = viewportH - edgeGap - chromeH - VIEWPORT_MARGIN;
  const visRows = open ? settings.bigRows : settings.smallRows;
  const wantH = visRows * ROW_H;
  const bodyH = Math.max(ROW_H, Math.min(wantH, room));

  const placedStyle: React.CSSProperties | undefined = placed
    ? dock.anchor === "bottom"
      ? { left: dock.x!, bottom: dock.y!, top: "auto", right: "auto" }
      : { left: dock.x!, top: dock.y!, bottom: "auto", right: "auto" }
    : undefined;

  return (
    <div
      ref={panelRef}
      style={placedStyle}
      className={cn(
        "fixed z-40 hidden w-[290px] flex-col bg-panel border border-border rounded-lg shadow-xl overflow-hidden",
        onMessagesPro ? "lg:flex" : "md:flex",
        !placed && (onMessagesPro ? "bottom-0 left-0 w-100 rounded-none border-l-0 border-b-0 shadow-none" : "bottom-3 right-[88px]"),
      )}
    >
      <div
        onPointerDown={onHeaderPointerDown}
        title="Drag to move"
        className="flex items-center gap-1 pr-2 bg-bg-elev-1/50 border-b border-border cursor-grab active:cursor-grabbing touch-none select-none"
      >
        <button
          type="button"
          onClick={toggle}
          className="flex items-center gap-2 flex-1 min-w-0 px-3 py-2 hover:bg-bg-elev-1 text-left"
          title={open ? "Collapse" : "Expand"}
          aria-expanded={open}
        >
          <span className="text-[11px] text-fg-dim w-3 shrink-0" aria-hidden>
            {open ? "⌄" : ">"}
          </span>
          <span className="text-[12px] font-medium text-fg flex items-center gap-1.5 truncate">
            <span aria-hidden>💰</span> Buys &amp; tips
            <span
              className={cn(
                "shrink-0 px-1 min-w-[16px] h-[14px] rounded-full text-[9px] font-semibold grid place-items-center",
                unseen > 0
                  ? "bg-ok text-white"
                  : "bg-bg-elev-1 text-fg-dim border border-border",
              )}
              title={
                unseen > 0
                  ? `${unseen} new sale${unseen === 1 ? "" : "s"} since you last looked`
                  : "No new sales since you last looked"
              }
            >
              {unseen}
            </span>
            {anyRefreshing && (
              <span className="text-fg-dim animate-pulse" title="Refreshing…" aria-hidden>↻</span>
            )}
          </span>
        </button>
        <button
          type="button"
          onClick={() => {
            if (swallowClick()) return;
            // a drag released over this button must not also open a group tab
            void openGroupTabWithSlots(groupSlots);
          }}
          disabled={groupSlots.length === 0}
          className="shrink-0 px-1.5 py-1 rounded text-[11px] text-fg-dim hover:text-fg hover:bg-bg-elev-1 disabled:opacity-40 disabled:hover:bg-transparent"
          title={`Open the last ${Math.min(groupSlots.length, GROUP_SLOT_CAP)} payers in the group tab (click again to refresh it)`}
        >
          <span aria-hidden>👥</span> {groupSlots.length}
        </button>
        <button
          type="button"
          onClick={() => {
            if (swallowClick()) return;
            setSettingsOpen((v) => !v);
          }}
          className={cn(
            "shrink-0 px-1.5 py-1 rounded text-[11px] hover:text-fg hover:bg-bg-elev-1",
            settingsOpen ? "text-fg bg-bg-elev-1" : "text-fg-dim",
          )}
          title="Rail settings"
          aria-expanded={settingsOpen}
        >
          <span aria-hidden>⚙</span>
        </button>
      </div>

      {settingsOpen && (
        <SettingsPanel
          settings={settings}
          accounts={activeAccounts}
          onChange={onSettingsChange}
        />
      )}
      {visRows > 0 && (
        <div
          style={{ maxHeight: bodyH }}
          className="overflow-y-auto overscroll-contain"
        >
          {anyLoading && merged.length === 0 && (
            <div className="px-3 py-2.5 text-[11px] text-fg-dim">Loading…</div>
          )}
          {merged.length === 0 && !anyLoading && (
            <div className="px-3 py-2.5 text-[11px] text-fg-dim">
              No recent purchases or tips.
            </div>
          )}
          {merged.map((m, i) => {
            const fanId = payerIdOf(m);
            const key = `${m.accountId}:${m.n.id ?? i}`;
            return (
              <Row
                key={key}
                leaseRef={track(m.accountId, key)}
                m={m}
                accountLabel={showAccountTag ? (accountLabel.get(m.accountId) ?? null) : null}
                reply={fanId ? (replyStates.get(`${m.accountId}:${fanId}`) ?? null) : null}
                dim={placeholderAids.has(m.accountId)}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}
