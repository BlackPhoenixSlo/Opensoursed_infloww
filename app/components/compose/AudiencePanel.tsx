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
import { IfHelp, IfLabel } from "@/components/ui/infloww";

import type { MassAction, MassForm } from "./massMessageReducer";

/** A list column's heading (under the Audience label). */
const SUB = "mb-1.5 text-[12px] text-fg-dim";

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
    <div className="space-y-3">
      <div>
        <IfLabel required>Audience</IfLabel>
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
        <IfHelp>Default: fans + following both included (click to toggle).</IfHelp>
      </div>
      {!allModels && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <div className={SUB}>Custom lists — include</div>
            <ListColumn
              lists={customLists}
              loading={listsLoading}
              selected={includes}
              onToggle={(id) => dispatch({ type: "toggleInclude", id })}
              emptyLabel="No custom lists."
            />
          </div>
          <div>
            <div className={SUB}>Custom lists — exclude</div>
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
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
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
        <div className="text-[12px] text-muted">
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
      <div className={SUB}>{title}</div>
      <div className="flex flex-wrap gap-1.5">
        {lists.map((l) => (
          <button
            key={l.id}
            type="button"
            aria-pressed={selected.has(l.id)}
            onClick={() => onToggle(l.id)}
            className={`h-7 rounded-full border px-3 text-[12px] transition-colors ${
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
