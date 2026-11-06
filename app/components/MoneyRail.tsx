"use client";

/**
 * MoneyRail — sticky bottom-right dock for money notifications (purchases
 * + tips) so chatters can jump straight to the fans who just paid. In
 * Messages Pro it docks at the Fan List's foot instead (page-parity 07 CP8).
 *
 * TWO components, on purpose. `MoneyRail` is a gate: it owns the surface and
 * the settings and nothing else, and mounts `MoneyRailPanel` only where the
 * rail is meant to appear. Everything below — the fetches, the dock, the
 * drag — lives in the panel and may assume it is on a surface the user asked
 * for. See the gate's own note for why that boundary has to be a mount and
 * can't be a flag.
 *
 * It fetches OF's /notifications?type=purchases|tip on mount — collapsed or
 * not — so the rail is fresh on first page load rather than only after the
 * user expands it. Those rows are merged with the localStorage notif-history
 * mirror (which carries SSE arrivals that OF hasn't listed yet). Uses the SAME
 * ["notif-list", aid, type] query keys as the bell, so the cache is shared.
 * The OF call budget and the cold start are `useMoneyRailFeed`'s (its header).
 *
 * WHICH MODELS: every active one by default, deliberately ignoring the
 * ScopeContext the rest of the UI follows — money landing on the model you're
 * NOT looking at is exactly what you don't want to miss. Narrow it in ⚙.
 *
 * Two sizes, and the marker (">" / "⌄") points where a click takes you.
 * Collapsing SHRINKS THE WINDOW, it doesn't truncate the feed — every row
 * stays mounted and scrolls, so "small" shows 1 row (configurable 0-4, where
 * 0 collapses to just the header bar) with the rest a flick away, and "big"
 * shows 6 (configurable 5-8). Which SURFACES show the rail at all (inbox /
 * solo chat pop-out / group tab / everything else) is also a ⚙ choice — the
 * house default keeps it on the chat surfaces and off the admin pages. A
 * rail hidden on the current surface is restorable from the 🔔 dropdown,
 * which is mounted everywhere. The header always carries the count of sales
 * that arrived since the rows were last on screen.
 *
 * Draggable by its header. Position + the collapsed/expanded bit are persisted
 * PER SURFACE (inbox / chat pop-out / group tab): the rail is mounted once in
 * the root layout, but a corner that's out of the way in the inbox can cover a
 * pane in the group tab, so each surface remembers its own. Row counts and the
 * model pick are global — they're about the work, not this window's layout.
 * Dragging over the header's buttons doesn't fire them.
 *
 * Sticky by design: it never closes on outside click or Escape — only
 * tapping the header toggles it. Rows deep-link to the fan's chat with
 * the one-shot ?refresh=media flag (same as money toasts) since the fan
 * just moved money and the popout's persisted caches are stale by seconds.
 * A row opens like any notification (lib/notificationLink): the fan in a Fan
 * tab of Messages Pro, in place there, else in the Messages Pro window.
 */

import { usePathname } from "next/navigation";

import { useRailSettings } from "@/hooks/useRailSettings";
import { lazyModule, useLazyModule } from "@/lib/lazyModule";
import { parseSurfaces, railVisibleOn, surfaceOf } from "@/lib/moneyRailStorage";

/** The panel (its feed, rows, dock and ⚙) is fetched once the gate passes: on most surfaces it never mounts, and
 *  the bell's restore button needs only this file (MoneyRailPanel.tsx). */
const railPanel = lazyModule(() => import("./MoneyRailPanel"));

/**
 * Money-rail rescue hatch: hiding the rail on a surface takes its ⚙ (the
 * only un-hide control) down with it. The 🔔 bell is mounted everywhere, so
 * it renders this inside its dropdown to offer the way back when the rail is
 * hidden on the CURRENT surface. Self-contained — it owns the surface read,
 * the hidden-here check and the restore write, and returns null when the rail
 * isn't hidden here, so hosts can mount it unconditionally.
 */
export function MoneyRailRestoreButton() {
  const surface = surfaceOf(usePathname());
  const { settings, commit } = useRailSettings();
  const showHere = () => {
    if (!settings) return;
    // Adding the last missing surface normalises to null (= everywhere).
    commit({
      ...settings,
      surfaces: parseSurfaces([...(settings.surfaces ?? []), surface]),
    });
  };
  if (!settings || railVisibleOn(settings, surface)) return null;
  return (
    <button
      type="button"
      onClick={showHere}
      className="w-full text-left px-3 py-1.5 text-[11px] border-b border-border text-fg-dim hover:text-fg hover:bg-bg-elev-1 flex items-center gap-1.5"
      title="The Buys & tips rail is hidden on this page — bring it back"
    >
      <span aria-hidden>💰</span>
      <span className="truncate">
        Buys &amp; tips rail is hidden here —{" "}
        <span className="text-info">show it on this page</span>
      </span>
    </button>
  );
}

/**
 * The rail is mounted once in the ROOT layout, so it is on every route, but
 * `settings.surfaces` decides where it actually appears. That decision lives
 * HERE, in a parent that owns nothing else, rather than inside the panel:
 * hooks can't be conditional, so a panel that judged its own visibility would
 * judge it only AFTER every fetch, effect, listener and cache subscription it
 * declares had already fired — which is exactly what it used to do, paying
 * ~14 OF round-trips on each of the 8 routes where it then painted nothing.
 * A gate makes that structurally impossible instead of individually gated:
 * on a surface the user didn't tick, MoneyRailPanel never mounts, so there is
 * nothing to remember to switch off.
 */
export function MoneyRail() {
  const surface = surfaceOf(usePathname());
  const { settings, commit } = useRailSettings();
  const show = !!settings && railVisibleOn(settings, surface);
  const panel = useLazyModule(railPanel, show);
  if (!settings || !show || !panel) return null;
  return <panel.MoneyRailPanel surface={surface} settings={settings} onSettingsChange={commit} />;
}
