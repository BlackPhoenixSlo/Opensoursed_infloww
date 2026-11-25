"use client";


import { type ChangeEvent, useEffect, useId, useRef, useState } from "react";

import { useMassExclude } from "@/hooks/useMassExclude";
import { type FanId } from "@/lib/fanId";
import { MP } from "@/lib/messagesPro";
import { extraTitle } from "@/lib/openinflowwwwExtras";
import { type FanRecord } from "@/lib/relay";
import { cn, fmtRelTime, type SubStatusDisplay } from "@/lib/utils";
import { MENU, MENU_ITEM, MENU_ROW } from "./MenuParts";
import { type InsightsBlockId } from "./useInsightsBlocks";
import { InfoTip } from "@/components/ui/InfoTip";
import { IfDateInput } from "@/components/ui/ifDateInput";

// Excluded fans still get welcomes / AI replies / manual 1:1s; only mass sends skip them.
export function MassExcludeToggle({
  accountId, fanId, title, hint,
}: {
  accountId: string; fanId: FanId; title: string; hint: string;
}) {
  const { isOn, isLoading, toggle } = useMassExclude(accountId, fanId);
  return (
    <div title={extraTitle("Mass exclude")} className="flex items-center justify-between gap-3 rounded-md border border-border bg-bg px-2.5 py-2">
      <div className="min-w-0">
        <div className="text-xs font-medium text-fg flex items-center gap-1.5">
          <span>🚫</span> {title}
        </div>
        <div className={cn(MP.ours.FanDrawer.excludeHint, "hidden md:block text-fg-dim")}>{hint}</div>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={isOn}
        disabled={isLoading || toggle.isPending}
        onClick={() => toggle.mutate(!isOn)}
        title={isOn ? `Remove from ${title}` : `Add to ${title}`}
        className={cn(
          "relative shrink-0 w-12 h-7 md:w-10 md:h-6 rounded-full transition-colors disabled:opacity-50",
          isOn ? "bg-accent" : "bg-bg-elev-1 border border-border",
        )}
      >
        <span
          className={cn(
            "absolute top-0.5 left-0.5 w-6 h-6 md:w-5 md:h-5 rounded-full bg-white shadow transition-transform",
            isOn ? "translate-x-5 md:translate-x-4" : "translate-x-0",
          )}
        />
      </button>
    </div>
  );
}

export function useFocusRequest<T extends HTMLElement>(request: number | undefined, onAsk: () => void, ready: unknown) {
  const ref = useRef<T>(null);
  const focusedRef = useRef(0);
  const [asked, setAsked] = useState(0);
  if ((request ?? 0) > asked) {
    setAsked(request ?? 0);
    onAsk();
  }
  // The hidden twin's field is display:none and cannot take focus, so only the visible instance does.
  useEffect(() => {
    const field = ref.current;
    if (asked <= focusedRef.current || !field) return;
    focusedRef.current = asked;
    field.scrollIntoView?.({ block: "nearest" });
    field.focus({ preventScroll: true });
  }, [asked, ready]);
  return { ref, asked };
}

export const BLOCK_TITLE: Record<InsightsBlockId, string> = {
  spending: "Spending behavior", org: "Organization metrics", subscription: "Subscription",
  profile: "Profile", lists: "Lists", notes: "Notes",
  fan: "Fan", massExclude: "Mass exclude", unsoldPpvs: "Unsold PPVs sent",
};

export type InsightsTab = "insights" | "sales" | "notes";
export const INSIGHTS_TABS: InsightsTab[] = ["insights", "sales", "notes"];
export const TAB_LABEL: Record<InsightsTab, string> = { insights: "Insights", sales: "Sales", notes: "Notes" };
export const TAB_HINT: Record<InsightsTab, string> = {
  insights: "Fan insights: profile, spending and more",
  sales: "Sales: this fan's PPVs and purchases",
  notes: "Notes about this fan",
};
const TAB_TITLE: Record<InsightsTab, string> = { insights: "Fan insights", sales: "Sales", notes: "Notes" };
export const TAB_ICON: Record<InsightsTab, React.ReactNode> = {
  insights: (
    <svg aria-hidden viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className={MP.insights.tabIcon}>
      <path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7z" /><circle cx="12" cy="12" r="2.6" />
    </svg>
  ),
  sales: (
    <svg aria-hidden viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className={MP.insights.tabIcon}>
      <path d="M20.6 13.4L13 21l-9-9V4h8l8.6 8.6a1.5 1.5 0 0 1 0 .8z" />
      <circle cx="8" cy="8" r="1.3" fill="currentColor" stroke="none" />
    </svg>
  ),
  notes: (
    <svg aria-hidden viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className={MP.insights.tabIcon}>
      <path d="M6 3h12a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z" /><path d="M8 8h8M8 12h8M8 16h5" />
    </svg>
  ),
};

export function InsightsHead({ uid, tab, setTab, blocks, onClose, addOpen, setAddOpen, addRef }: {
  uid: string; tab: InsightsTab; setTab: (t: InsightsTab) => void;
  blocks: { removed: InsightsBlockId[]; add: (id: InsightsBlockId) => void }; onClose: () => void;
  addOpen: boolean; setAddOpen: React.Dispatch<React.SetStateAction<boolean>>; addRef: React.RefObject<HTMLDivElement | null>;
}) {
  return (
    <header className={cn(MP.insights.head, MP.ours.FanDrawer.head, "flex items-center")}>
      <h2 className="flex-1 min-w-0 truncate leading-6">{TAB_TITLE[tab]}</h2>
      <div ref={addRef} className="relative shrink-0">
        <button
          type="button"
          onClick={() => setAddOpen((o) => !o)}
          aria-expanded={addOpen}
          aria-haspopup="menu"
          aria-controls={addOpen ? `${uid}-add` : undefined}
          aria-label="Add block"
          title="Add a removed block back"
          className={cn(
            "grid place-items-center w-11 h-11 md:w-6 md:h-6 -my-2 md:my-0 rounded-md text-2xl md:text-lg font-normal leading-none hover:text-fg",
            addOpen ? "text-[var(--inf-accent-text,var(--color-accent))]" : "text-fg-dim",
          )}
        >
          +
        </button>
        {addOpen && (
          <div id={`${uid}-add`} role="menu" aria-label="Add block" className={cn(MENU, MP.ours.FanDrawer.addMenu)}>
            {blocks.removed.length === 0 ? (
              <div className={cn(MENU_ROW, "text-fg-dim")}>Every block is shown</div>
            ) : blocks.removed.map((id) => (
              <button
                key={id}
                type="button"
                role="menuitem"
                onClick={() => { blocks.add(id); setTab("insights"); setAddOpen(false); }}
                className={MENU_ITEM}
              >
                {BLOCK_TITLE[id]}
              </button>
            ))}
          </div>
        )}
      </div>
      <button
        type="button"
        onClick={onClose}
        className="shrink-0 grid place-items-center w-11 h-11 md:w-6 md:h-6 -my-2 md:my-0 -mr-2 md:mr-0 text-2xl md:text-lg font-normal leading-none text-fg-dim hover:text-fg"
        aria-label="Close"
        title="Close Fan insights"
      >
        ×
      </button>
    </header>
  );
}

export function NickEdit({ children }: { children: React.ReactNode }) {
  return (
    <span className={cn(MP.insights.nickEdit, "flex items-center justify-end")}>
      {children}
      <svg aria-hidden viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"
           className={cn(MP.insights.pencil, "shrink-0 text-fg-dim")}>
        <path d="M14 4l6 6L8 22H2v-6z" />
      </svg>
    </span>
  );
}

export const RULE = cn(MP.insights.rule, MP.ours.FanDrawer.rule, "bg-border");

export const INLINE_EDIT = cn(
  MP.ours.FanDrawer.inlineEdit,
  "min-w-0 flex-1 bg-transparent text-right focus:outline-none focus:ring-1 focus:ring-accent",
);

export const MM_DD = /^(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$/;

export function BlurEdit({ id, saved, type = "text", pattern, inputMode, maxLength, placeholder, title, onSave }: {
  id: string; saved: string | null; type?: "text" | "date"; pattern?: RegExp;
  inputMode?: "numeric"; maxLength?: number; placeholder?: string; title?: string;
  onSave: (value: string | null) => void;
}) {
  const [value, setValue] = useState(saved ?? "");
  const field = {
    id, inputMode, maxLength, value, placeholder, title,
    onChange: (e: ChangeEvent<HTMLInputElement>) => setValue(e.target.value),
    onBlur: () => {
      const v = value.trim();
      if (v === (saved ?? "")) return;
      if (v && pattern && !pattern.test(v)) { setValue(saved ?? ""); return; }
      onSave(v || null);
    },
    className: INLINE_EDIT,
  };
  return (
    <NickEdit>
      {type === "date" ? <IfDateInput type="date" {...field} /> : <input type="text" {...field} />}
    </NickEdit>
  );
}

export function LocalTime({ zone }: { zone: string | null }) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    setNow(new Date());
    if (!zone) return;
    const t = setInterval(() => setNow(new Date()), 60_000);
    return () => clearInterval(t);
  }, [zone]);
  if (!zone) return <>—</>;
  return (
    <span title={zone}>
      {now.toLocaleTimeString([], { timeZone: zone, hour: "numeric", minute: "2-digit" })}
    </span>
  );
}

type Tone = SubStatusDisplay["tone"];

const TONE_CLASS: Record<Tone, string> = {
  ok: "text-ok", warn: "text-warn", err: "text-err", "fg-dim": "text-fg-dim",
};
export function toneClass(tone: Tone): string {
  return TONE_CLASS[tone];
}

export type BlockCard = {
  onDragStart: (e: React.DragEvent) => void;
  onDragOver: (e: React.DragEvent) => void;
  onDrop: (e: React.DragEvent) => void;
  onDragEnd: (e: React.DragEvent) => void;
  onMove: (dir: -1 | 1) => void;
  dragging: boolean;
  over: boolean;
  onRemove: () => void;
};

export function InsightsBlock({
  title, plainTitle, lead, children, trail, card,
}: {
  title: string;
  plainTitle?: boolean;
  lead?: React.ReactNode;
  children?: React.ReactNode;
  trail?: React.ReactNode;
  card?: BlockCard;
}) {
  const [expanded, setExpanded] = useState(true);
  const id = useId();
  const grip = (
    <svg aria-hidden viewBox="0 0 24 24" fill="currentColor" className={MP.insights.dragIcon}>
      <circle cx="9" cy="6" r="1.4" /><circle cx="15" cy="6" r="1.4" />
      <circle cx="9" cy="12" r="1.4" /><circle cx="15" cy="12" r="1.4" />
      <circle cx="9" cy="18" r="1.4" /><circle cx="15" cy="18" r="1.4" />
    </svg>
  );
  return (
    <section
      aria-labelledby={`${id}-title`}
      onDragOver={card?.onDragOver}
      onDrop={card?.onDrop}
      className={cn(
        MP.insights.block,
        "bg-[var(--inf-card,var(--color-bg-elev-1))] border-[var(--inf-card-border,var(--color-border))]",
        card?.dragging && "opacity-50",
        card?.over && "border-accent",
      )}
    >
      <div className={cn(expanded ? MP.insights.blockHead : MP.ours.FanDrawer.blockHeadCollapsed, "flex items-center")}>
        {card ? (
          <button
            type="button"
            draggable
            onDragStart={(e) => {
              const block = e.currentTarget.closest("section");
              if (block) e.dataTransfer.setDragImage?.(block, 0, 0);
              card.onDragStart(e);
            }}
            onDragEnd={card.onDragEnd}
            onKeyDown={(e) => {
              if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
              e.preventDefault();
              card.onMove(e.key === "ArrowUp" ? -1 : 1);
            }}
            aria-label={`Move ${title}`}
            title="Drag to move (↑/↓ from the keyboard)"
            className="shrink-0 text-fg-dim hover:text-fg cursor-grab active:cursor-grabbing"
          >
            {grip}
          </button>
        ) : (
          <span title="not wired" className="shrink-0 text-fg-dim">{grip}</span>
        )}
        {plainTitle
          ? <span id={`${id}-title`} className={cn(MP.insights.blockTitle, "flex-1 min-w-0")}>{title}</span>
          : <h3 id={`${id}-title`} className={cn(MP.insights.blockTitle, "flex-1 min-w-0")}>{title}</h3>}
        {card && (
          <button
            type="button"
            onClick={card.onRemove}
            aria-label={`Remove ${title}`}
            title={`Remove ${title} (the head's + adds it back)`}
            className="shrink-0 text-fg-dim hover:text-fg"
          >
            <svg aria-hidden viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9"
                 className={MP.insights.chevron}>
              <path d="M7 7l10 10M17 7L7 17" />
            </svg>
          </button>
        )}
        <button
          type="button"
          onClick={() => setExpanded((e) => !e)}
          aria-expanded={expanded}
          aria-label={`${expanded ? "Collapse" : "Expand"} ${title}`}
          title={`${expanded ? "Collapse" : "Expand"} ${title}`}
          className="shrink-0 text-fg-dim hover:text-fg"
        >
          <svg aria-hidden viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9"
               className={cn(MP.insights.chevron, !expanded && "rotate-180")}>
            <path d="M6 15l6-6 6 6" />
          </svg>
        </button>
      </div>
      {expanded && <>{lead}{children && <dl>{children}</dl>}{trail}</>}
    </section>
  );
}

export function InsightsRow({ term, value }: { term: React.ReactNode; value: React.ReactNode }) {
  return (
    <div className={cn(MP.insights.metric, MP.ours.FanDrawer.row, "flex items-start justify-between")}>
      <dt className={cn(MP.insights.metricKey, MP.ours.FanDrawer.term, "flex items-center text-fg-dim")}>{term}</dt>
      <dd className={cn(MP.insights.metricPlain, "min-w-0 flex-1 text-right")}>{value}</dd>
    </div>
  );
}

export function Badge({ children }: { children: React.ReactNode }) {
  return (
    <span className={cn(MP.insights.badge, "inline-block bg-bg-elev-2")}>
      {children}
    </span>
  );
}

export function InfoIcon({ title }: { title: string }) {
  return (
    <InfoTip text={title} icon={
      <svg aria-hidden viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"
           className={cn(MP.insights.info, "shrink-0")}>
        <circle cx="12" cy="12" r="9" /><path d="M12 11v5M12 8h.01" strokeLinecap="round" />
      </svg>
    } />
  );
}

// OF status semantics: "Set to Expire" does not renew, an expired sub cannot.
export function autoRenewal(status: SubStatusDisplay): string {
  if (status.expired || status.short === "Won't renew") return "Off";
  if (status.short === "Active") return "On";
  return "—";
}

// Picking a language pins it MANUAL so gen_info's auto-detection never changes it.
export const LANGUAGE_OPTIONS: { code: string; label: string }[] = [
  { code: "en", label: "English" },
  { code: "es", label: "Español" },
  { code: "sl", label: "Slovenščina" },
  { code: "pt", label: "Português" },
  { code: "fr", label: "Français" },
  { code: "de", label: "Deutsch" },
  { code: "it", label: "Italiano" },
];

export function languageHint(language: string | null, source: string | null): string {
  if (!language) return "Using the account default. Pick one to pin this fan.";
  if (source === "manual") return "Manual override — auto-detection won't change it.";
  return "Auto-detected. Pick one to pin it (stops auto-detection).";
}

const LANG_LABEL: Record<string, string> = Object.fromEntries(LANGUAGE_OPTIONS.map(l => [l.code, l.label]));

function fmtCommStyle(cs: Record<string, unknown> | undefined): string {
  if (!cs) return "";
  return Object.entries(cs).filter(([, v]) => v === true).map(([k]) => k.replace(/_/g, " ")).join(", ");
}

function petLabel(p: unknown): string {
  if (p && typeof p === "object") {
    const o = p as Record<string, unknown>;
    return [o.kind, o.name].filter(Boolean).join(" ") || JSON.stringify(o);
  }
  return String(p);
}

export function ProfileCard({ fan }: { fan: FanRecord }) {
  const p = fan.profile;
  const facts: [string, string | null | undefined][] = [
    ["Age", fan.his_age],
    ["Location", [fan.home_city, fan.home_country].filter(Boolean).join(", ") || null],
    ["Job", fan.occupation],
    ["Employer", fan.employer],
    ["Relationship", fan.relationship_status],
    ["Stage", fan.relationship_stage],
    ["Kids", fan.has_kids == null ? null : fan.has_kids ? "yes" : "no"],
    ["Pets", Array.isArray(fan.pets) && fan.pets.length ? fan.pets.map(petLabel).join(", ") : null],
    ["Style", fmtCommStyle(fan.communication_style) || null],
  ];
  const shown = facts.filter(([, v]) => v);
  const timeline = (fan.recent_events_timeline ?? []).filter((t) => t?.event);
  const richNote = p?.rich_note?.trim();
  const langCode = fan.language ?? "";
  const nothing = !richNote && shown.length === 0 && timeline.length === 0 &&
    !(p?.q?.length) && !(p?.tease?.length);

  return (
    <div title={extraTitle("Generated profile note")} className="rounded-lg border border-[var(--inf-card-border,var(--color-border))] bg-[var(--inf-card,var(--color-bg-elev-1))]/40 p-3">
      <div className="flex items-center justify-between mb-2">
        <span className={cn(MP.ours.FanDrawer.sectionHeading, "text-fg-dim uppercase")}>AI profile</span>
        <div className="flex items-center gap-2">
          {langCode ? (
            <span className={cn(MP.ours.FanDrawer.langChip, "border-border text-fg-dim")}
              title={fan.language_source === "manual" ? "Manual override" : "Auto-detected"}>
              🌐 {LANG_LABEL[langCode] ?? langCode}
              {fan.language_source === "manual" ? " · pinned" : ""}
            </span>
          ) : null}
          {p?.last_generated_at ? (
            <span className={cn(MP.ours.FanDrawer.profileMeta, "text-fg-dim")}>{fmtRelTime(p.last_generated_at)}</span>
          ) : null}
        </div>
      </div>

      {nothing ? (
        <div className={cn(MP.ours.FanDrawer.profileText, "text-fg-dim")}>No profile yet — gen_info fills this once he chats a little.</div>
      ) : (
        <div className="flex flex-col gap-3">
          {richNote ? (
            <div className={cn(MP.ours.FanDrawer.profileNote, "text-fg whitespace-pre-line")}>{richNote}</div>
          ) : null}

          {shown.length ? (
            <div className="grid grid-cols-2 gap-x-3 gap-y-1">
              {shown.map(([k, v]) => (
                <div key={k} className={MP.ours.FanDrawer.profileText}>
                  <span className="text-fg-dim">{k}: </span><span className="text-fg">{v}</span>
                </div>
              ))}
            </div>
          ) : null}

          {timeline.length ? (
            <div>
              <div className={cn(MP.ours.FanDrawer.timelineLabel, "text-fg-dim uppercase")}>Timeline</div>
              <ul className="space-y-0.5">
                {timeline.slice(-6).reverse().map((t, i) => (
                  <li key={i} className={cn(MP.ours.FanDrawer.profileText, "text-fg-dim")}>
                    <span className={cn(MP.ours.FanDrawer.profileMeta, "font-mono")}>{t.date}</span> · <span className="text-fg">{t.event}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {p?.q?.length || p?.tease?.length ? (
            <div className={cn(MP.ours.FanDrawer.profileMeta, "text-fg-dim")}>
              {p?.q?.length ? <div>{p.q.length} question{p.q.length > 1 ? "s" : ""} + {p?.tease?.length ?? 0} tease{(p?.tease?.length ?? 0) > 1 ? "s" : ""} ready</div> : null}
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}
