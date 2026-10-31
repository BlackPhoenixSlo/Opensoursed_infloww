"use client";

/**
 * AudiencePanel — MassMessageComposer's audience picker: the system audiences
 * (include-only chips), the account's custom lists and Smart Lists (include /
 * exclude columns, one account only) and the reach hint. Pure view: the picks
 * are the form's (massMessageReducer), every click a dispatch. In all-models
 * mode only the system audiences show — custom lists and segments are
 * per-account, so no id means the same thing across every model.
 */

import type { Dispatch } from "react";

import { ListColumn, SYSTEM_AUDIENCES, SysChip, type FanList } from "@/components/audience/fanLists";
import type { SmartList } from "@/hooks/useSmartLists";

import type { MassAction, MassForm } from "./massMessageReducer";

export function AudiencePanel({
  form, dispatch, customLists, listsLoading, smartLists,
}: {
  form: Pick<MassForm, "allModels" | "includes" | "excludes" | "smartInclude" | "smartExclude">;
  dispatch: Dispatch<MassAction>;
  customLists: FanList[];
  listsLoading: boolean;
  smartLists: SmartList[];
}) {
  const { allModels, includes, excludes, smartInclude, smartExclude } = form;
  // Reach preview — sum the user-count of the custom lists we're including
  // (system audiences don't expose counts, so we hint them separately).
  const includeReach = Array.from(includes).reduce((sum, id) => {
    const l = customLists.find((x) => String(x.id) === id);
    return sum + (l?.usersCount ?? 0);
  }, 0);
  const hasSystem = Array.from(includes).some((id) => SYSTEM_AUDIENCES.some((b) => b.id === id));

  return (
    <div className="border border-border rounded-md p-3 space-y-3">
      <div className="text-[11px] uppercase tracking-wide text-fg-dim">
        Audience <span className="text-err">*</span>
      </div>
      <div className="space-y-1.5">
        <div className="flex flex-wrap gap-1.5">
          {SYSTEM_AUDIENCES.map((b) => (
            // Include-only: OF ignores system audiences in `excludedLists`,
            // so there is no "exclude" state to offer (see cycleSystem).
            <SysChip
              key={b.id}
              state={includes.has(b.id) ? "in" : "off"}
              onClick={() => dispatch({ type: "cycleSystem", id: b.id })}
              label={b.label}
            />
          ))}
        </div>
        <div className="text-[10px] text-fg-dim">
          Default: fans + following both included (click to toggle).
        </div>
      </div>
      {!allModels && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-2 border-t border-border/60">
          <div>
            <div className="text-[11px] text-fg-dim mb-1.5">Custom lists — include</div>
            <ListColumn
              lists={customLists}
              loading={listsLoading}
              selected={includes}
              onToggle={(id) => dispatch({ type: "toggleInclude", id })}
              emptyLabel="No custom lists."
            />
          </div>
          <div>
            <div className="text-[11px] text-fg-dim mb-1.5">Custom lists — exclude</div>
            <ListColumn
              lists={customLists}
              loading={listsLoading}
              selected={excludes}
              onToggle={(id) => dispatch({ type: "toggleExclude", id })}
              emptyLabel="—"
            />
          </div>
        </div>
      )}
      {/* Smart Lists — saved dynamic segments, resolved to fan ids on send. */}
      {!allModels && smartLists.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-2 border-t border-border/60">
          <SmartListColumn
            title="Smart Lists — include"
            lists={smartLists}
            selected={smartInclude}
            onToggle={(id) => dispatch({ type: "toggleSmartInclude", id })}
            onClass="bg-accent text-white border-accent"
          />
          <SmartListColumn
            title="Smart Lists — exclude"
            lists={smartLists}
            selected={smartExclude}
            onToggle={(id) => dispatch({ type: "toggleSmartExclude", id })}
            onClass="bg-err/20 text-err border-err/40"
          />
        </div>
      )}
      {!allModels && (includes.size > 0 || excludes.size > 0) && (
        <div className="text-[11px] text-fg-dim border-t border-border/60 pt-2">
          Reach: {includeReach} fan{includeReach === 1 ? "" : "s"} from custom
          {hasSystem ? " + system audience" : ""}
          {excludes.size > 0 && ` — minus ${excludes.size} list${excludes.size === 1 ? "" : "s"}`}
        </div>
      )}
    </div>
  );
}

/** One side of the Smart List picker: a toggle chip per segment. */
function SmartListColumn({
  title, lists, selected, onToggle, onClass,
}: {
  title: string;
  lists: SmartList[];
  selected: ReadonlySet<number>;
  onToggle: (id: number) => void;
  /** The chip's classes while picked. */
  onClass: string;
}) {
  return (
    <div>
      <div className="text-[11px] text-fg-dim mb-1.5">{title}</div>
      <div className="flex flex-wrap gap-1.5">
        {lists.map((l) => (
          <button
            key={l.id}
            type="button"
            aria-pressed={selected.has(l.id)}
            onClick={() => onToggle(l.id)}
            className={`px-2.5 py-1 rounded-full text-xs border transition-colors ${
              selected.has(l.id) ? onClass : "bg-bg-elev-1 text-fg-dim border-border hover:text-fg"
            }`}
          >
            {l.name}
          </button>
        ))}
      </div>
    </div>
  );
}
