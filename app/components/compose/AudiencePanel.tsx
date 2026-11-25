"use client";


import type { Dispatch } from "react";

import { ListColumn, SYSTEM_AUDIENCES, SysChip, type FanList } from "@/components/audience/fanLists";
import type { SmartList } from "@/hooks/useSmartLists";
import { IfHelp, IfLabel } from "@/components/ui/infloww";

import { reachHint } from "./audienceReach";
import type { MassAction, MassForm } from "./massMessageReducer";

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
  const reach = reachHint(form, customLists);

  return (
    <div className="space-y-3">
      <div>
        <IfLabel required>Audience</IfLabel>
        <div className="flex flex-wrap gap-1.5">
          {SYSTEM_AUDIENCES.map((b) => (
            // Include-only: OF ignores system audiences in `excludedLists`.
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
      {reach && <div className="text-[12px] text-muted">{reach}</div>}
    </div>
  );
}

function SmartListColumn({
  title, lists, selected, onToggle, onClass,
}: {
  title: string;
  lists: SmartList[];
  selected: ReadonlySet<number>;
  onToggle: (id: number) => void;
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
