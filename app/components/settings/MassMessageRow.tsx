"use client";


import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Lock, MoreHorizontal, Paperclip } from "lucide-react";

import { IF_TABLE } from "@/components/ui/infloww";
import type { MassMessageRow } from "@/hooks/useMassMessages";
import { SM, SM_MASS_ACTIONS } from "@/components/growth/smartMessagesControls";
import { MENU_ITEM, MENU_PANEL } from "@/components/ui/Menu";
import { proxyImage } from "@/lib/mediaUrl";
import { fmtCents } from "@/lib/messageFormat";
import { ofPlainText } from "@/lib/ofRichText";
import { cn } from "@/lib/utils";

const MASS_AUTOMATION_LABELS: Record<string, string> = {
  send_mass_message: "Mass message",
  reply_mass_funnel: "Funnel reply",
  mass_nudge: "Mass nudge",
  online_blast: "Online blast",
  ppv_send: "PPV Library",
};

function sentAt(iso: string, tz: string | null): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const opts: Intl.DateTimeFormatOptions = {
    month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit", hour12: true,
  };
  let parts: Intl.DateTimeFormatPart[];
  try {
    parts = new Intl.DateTimeFormat("en-US", { ...opts, timeZone: tz ?? undefined }).formatToParts(d);
  } catch {
    parts = new Intl.DateTimeFormat("en-US", opts).formatToParts(d);
  }
  const p = Object.fromEntries(parts.map((x) => [x.type, x.value]));
  return `${p.month} ${p.day}, ${p.year} at ${p.hour}:${p.minute} ${p.dayPeriod}`;
}

const SALES_TIP = "Purchases recorded on this broadcast's copies in our records (no OnlyFans read)";

function NotWiredCell() {
  return <td title="not wired" className={cn(IF_TABLE.td, "text-muted")}>—</td>;
}

export function MassMessageRowItem({
  m, accountLabel, reportTz, busy, onCancel,
}: {
  m: MassMessageRow;
  accountLabel: string;
  reportTz: string | null;
  busy: boolean;
  onCancel: () => void;
}) {
  const canUnsend = !!m.canUnsend && !m.isCanceled;
  const firstMedia = m.media?.[0];
  const thumbUrl =
    firstMedia?.files?.squarePreview?.url ||
    firstMedia?.files?.thumb?.url ||
    firstMedia?.files?.preview?.url ||
    null;
  const text = ofPlainText(m.text || m.rawText || "");
  const dash = <span className="text-fg-dim">--</span>;

  return (
    <tr className={cn(IF_TABLE.row, (busy || m.isCanceled) && "opacity-60")}>
      <td className={cn(IF_TABLE.td, "sticky left-0 bg-panel")}>
        {text
          ? <div className="truncate" title={text}>{text}</div>
          : <span className="text-fg-dim" title="This message contains only media">--</span>}
      </td>
      <td className={IF_TABLE.td}>{m.date ? sentAt(m.date, reportTz) : dash}</td>
      {m.automationKind ? (
        <td className={cn(IF_TABLE.td, "truncate")} title="Sent by an automation (joined via mass_runs)">
          {MASS_AUTOMATION_LABELS[m.automationKind] ?? m.automationKind}
          {m.funnelName ? ` · ${m.funnelName}` : ""}
        </td>
      ) : <NotWiredCell />}
      <td className={IF_TABLE.td}>
        {(m.mediaCount ?? 0) > 0 || m.giphyId ? (
          <span className="inline-flex items-center gap-2 text-fg-dim">
            {thumbUrl && (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={proxyImage(thumbUrl, m.__accountId)}
                alt=""
                className="w-8 h-8 rounded object-cover border border-border"
              />
            )}
            {(m.mediaCount ?? 0) > 0 && (
              <span className="inline-flex items-center gap-1"><Paperclip size={12} aria-hidden /> {m.mediaCount}</span>
            )}
            {m.giphyId && <span>GIF</span>}
          </span>
        ) : dash}
      </td>
      <td className={IF_TABLE.td}>
        <span
          className={cn(
            "inline-block rounded-2xl px-2 py-0.5 text-sm font-medium",
            m.isCanceled ? "bg-warn/15 text-warn" : "bg-accent/15 text-accent",
          )}
        >
          {m.isCanceled ? SM.massUnsent.label : SM.massSent.label}
        </span>
      </td>
      {m.isFree ? (
        <td className={IF_TABLE.td}>{dash}</td>
      ) : (
        <td title="not wired" className={IF_TABLE.td}>
          <span className="inline-flex items-center gap-1 text-warn"><Lock size={12} aria-hidden />PPV</span>
        </td>
      )}
      <td className={IF_TABLE.td}>{m.sentCount ?? 0}</td>
      <td className={IF_TABLE.td}>{m.viewedCount ?? 0}</td>
      <td className={IF_TABLE.td} title={SALES_TIP}>{m.isFree ? dash : (m.purchasedCount ?? 0)}</td>
      <td className={IF_TABLE.td} title={SALES_TIP}>{m.isFree ? dash : fmtCents(m.earningsCents ?? 0)}</td>
      <NotWiredCell />
      <NotWiredCell />
      <td className={cn(IF_TABLE.td, "truncate")}>{accountLabel}</td>
      <td className={cn(IF_TABLE.td, IF_TABLE.fixedRight, "z-[1] bg-panel px-1 text-center")}>
        <RowActionsMenu
          items={[
            {
              label: SM_MASS_ACTIONS.unsend.label,
              onClick: onCancel,
              disabled: busy || !canUnsend,
              title: m.isCanceled
                ? "Already unsent"
                : canUnsend
                ? SM_MASS_ACTIONS.unsendTip.label
                : "OF marked this as no-longer-unsendable",
            },
            { label: SM_MASS_ACTIONS.duplicate.label, disabled: true, title: "not wired" },
          ]}
        />
      </td>
    </tr>
  );
}

type RowAction = { label: string; onClick?: () => void; disabled: boolean; title: string };

function RowActionsMenu({ items }: { items: RowAction[] }) {
  const [pos, setPos] = useState<{ right: number; bottom: number } | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!pos) return;
    const close = () => setPos(null);
    const outside = (ev: MouseEvent) => {
      const t = ev.target as Node;
      if (!trigger.current?.contains(t) && !menu.current?.contains(t)) close();
    };
    const esc = (ev: KeyboardEvent) => { if (ev.key === "Escape") close(); };
    document.addEventListener("mousedown", outside);
    document.addEventListener("keydown", esc);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => {
      document.removeEventListener("mousedown", outside);
      document.removeEventListener("keydown", esc);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
    };
  }, [pos]);
  return (
    <>
      <button
        ref={trigger}
        type="button"
        aria-label="Actions"
        aria-haspopup="menu"
        aria-expanded={!!pos}
        onClick={() => {
          if (pos) return setPos(null);
          const r = trigger.current!.getBoundingClientRect();
          setPos({ right: window.innerWidth - r.right, bottom: window.innerHeight - r.top + 4 });
        }}
        className="inline-grid place-items-center w-6 h-6 rounded text-fg-dim hover:text-fg hover:bg-bg-elev-1"
      >
        <MoreHorizontal size={16} aria-hidden />
      </button>
      {pos && createPortal(
        <div
          ref={menu}
          role="menu"
          style={{ position: "fixed", right: pos.right, bottom: pos.bottom }}
          className={cn(MENU_PANEL, "mt-0 w-36 z-[60]")}
        >
          {items.map((it) => (
            <button
              key={it.label}
              type="button"
              role="menuitem"
              disabled={it.disabled}
              title={it.title}
              onClick={() => {
                setPos(null);
                it.onClick?.();
              }}
              className={cn(MENU_ITEM, it.disabled ? "text-fg-dim cursor-not-allowed opacity-60" : "hover:bg-bg-elev-1")}
            >
              {it.label}
            </button>
          ))}
        </div>,
        document.body,
      )}
    </>
  );
}
