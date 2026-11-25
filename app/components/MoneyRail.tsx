"use client";


import { usePathname } from "next/navigation";

import { useRailSettings } from "@/hooks/useRailSettings";
import { lazyModule, useLazyModule } from "@/lib/lazyModule";
import { parseSurfaces, railVisibleOn, surfaceOf } from "@/lib/moneyRailStorage";

const railPanel = lazyModule(() => import("./MoneyRailPanel"));

export function MoneyRailRestoreButton() {
  const surface = surfaceOf(usePathname());
  const { settings, commit } = useRailSettings();
  const showHere = () => {
    if (!settings) return;
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

// Gate must be a mount, not a flag in the panel: hooks can't be conditional, so a self-hiding panel would still fire its ~14 OF reads on every route.
export function MoneyRail() {
  const surface = surfaceOf(usePathname());
  const { settings, commit } = useRailSettings();
  const show = !!settings && railVisibleOn(settings, surface);
  const panel = useLazyModule(railPanel, show);
  if (!settings || !show || !panel) return null;
  return <panel.MoneyRailPanel surface={surface} settings={settings} onSettingsChange={commit} />;
}
