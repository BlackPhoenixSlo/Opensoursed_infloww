"use client";

/**
 * AgencyNotifications — the owner's agency notification centre (roadmap W6
 * 6.7), the "Agency" tab of the top bar's one bell (`NotificationBell`'s
 * `agency` slot, filled by TopBar's `HeaderBell`; Infloww's header has one
 * bell): role changes, deactivations, a chatter's unsent message, a missed
 * clock-in and a Creator logged out of OnlyFans, filed server-side by the
 * audit middleware and the periodic sweeps (service/notifications_api.py).
 *
 * Owner-only: a chatter's session never reads it (the routes refuse chatters).
 * The count is the server's unread, kept live by the owner-scoped
 * `agency_notifications` SSE event (useAccountStateEvents refetches this
 * query on it) with a slow safety poll; the bell adds it to its badge. A row
 * click marks it read; "Mark all read" reads the rest. The gear's switches
 * save the `notifications` key of the preferences blob — a kind switched off
 * is no longer filed. A row whose `data.href` names a page (a 2FA relink:
 * /creators?relink=browserbase) is a link to it; the click reads it too.
 */

import Link from "next/link";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Settings2 } from "lucide-react";

import { useUser } from "@/contexts/UserContext";
import { useChatter } from "@/contexts/ChatterContext";
import { relay } from "@/lib/relay";
import { ssePoll } from "@/lib/events";
import { useSettingsBlob } from "@/lib/settingsBlob";
import { cn } from "@/lib/utils";

export const AGENCY_NOTIFICATIONS_KEY = ["agency-notifications"] as const;

/** service/settings_schema.NOTIFICATION_KINDS, with their switch labels. */
export const KIND_LABELS = {
  role_changed: "Role changes",
  employee_deactivated: "Employee deactivations",
  message_unsent: "Unsent messages",
  clock_in_missed: "Missed clock-ins",
  session_dead: "Creator logged out",
} as const;
type Kind = keyof typeof KIND_LABELS;

export interface AgencyNotification {
  id: number;
  kind: string;
  text: string;
  account_id: string | null;
  employee_id: number | null;
  data: unknown;
  created_at: string;
  read: boolean;
}
interface ListResp { notifications: AgencyNotification[]; unread: number }

function useAgencyList(enabled: boolean) {
  return useQuery<ListResp>({
    queryKey: AGENCY_NOTIFICATIONS_KEY,
    queryFn: () => relay.get<ListResp>("/admin/agency-notifications?limit=30"),
    refetchInterval: ssePoll(300_000, 60_000),
    staleTime: 30_000,
    enabled,
  });
}

/** The owner's unread count for the bell's badge and its Agency tab, or null
 *  for anyone else (a chatter's session reads nothing; the routes refuse it). */
export function useAgencyUnread(): number | null {
  const { user } = useUser();
  const { chatter } = useChatter();
  const owner = !!user && !chatter;
  const q = useAgencyList(owner);
  return owner ? (q.data?.unread ?? 0) : null;
}

/** The Agency tab of the top bar's bell: "Mark all read", the kinds' gear and
 *  the rows. Mounted only for the owner (`useAgencyUnread` not null). */
export function AgencyFeed() {
  const qc = useQueryClient();
  const [settings, setSettings] = useState(false);
  const q = useAgencyList(true);
  const read = useMutation({
    mutationFn: (id: number | null) =>
      relay.post(id == null ? "/admin/agency-notifications/read-all" : `/admin/agency-notifications/${id}/read`),
    onSettled: () => void qc.invalidateQueries({ queryKey: AGENCY_NOTIFICATIONS_KEY }),
  });

  const unread = q.data?.unread ?? 0;
  const rows = q.data?.notifications ?? [];

  return (
    <div className="text-sm">
      <div className="flex items-center justify-end gap-2 px-3 py-2 border-b border-border text-xs">
        <button
          type="button"
          disabled={unread === 0 || read.isPending}
          onClick={() => read.mutate(null)}
          className="text-fg-dim hover:text-fg disabled:opacity-40"
        >
          Mark all read
        </button>
        <button
          type="button"
          onClick={() => setSettings((v) => !v)}
          aria-label="Notification settings"
          aria-pressed={settings}
          className="text-fg-dim hover:text-fg"
        >
          <Settings2 aria-hidden className="w-4 h-4" />
        </button>
      </div>
      {settings && <KindSwitches />}
      {q.isLoading && <div className="px-3 py-4 text-fg-dim">Loading…</div>}
      {!q.isLoading && rows.length === 0 && (
        <div className="px-3 py-6 text-center text-fg-dim">No agency notifications yet.</div>
      )}
      <ul>
        {rows.map((n) => {
          const onClick = () => { if (!n.read) read.mutate(n.id); };
          const cls = cn(
            "block w-full text-left px-3 py-2 border-b border-border/40 last:border-0 hover:bg-bg-elev-2",
            !n.read && "bg-accent/5",
          );
          const body = (
            <>
              <div className={cn("text-sm", n.read ? "text-fg-dim" : "text-fg font-medium")}>{n.text}</div>
              <div className="text-[11px] text-fg-dim mt-0.5">{when(n.created_at)}</div>
            </>
          );
          const href = hrefOf(n);
          return (
            <li key={n.id}>
              {href
                ? <Link href={href} onClick={onClick} className={cls}>{body}</Link>
                : <button type="button" onClick={onClick} className={cls}>{body}</button>}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/** The in-app page a notification points at (`data.href`, a path), else null. */
function hrefOf(n: AgencyNotification): string | null {
  const href = (n.data as { href?: unknown } | null)?.href;
  return typeof href === "string" && href.startsWith("/") && !href.startsWith("//") ? href : null;
}

/** Per-kind switches over `preferences.notifications` (absent = on). */
function KindSwitches() {
  const blob = useSettingsBlob<{ notifications?: Partial<Record<Kind, boolean>> }>("preferences", {});
  const current = blob.value.notifications ?? {};
  return (
    <div className="px-3 py-2 border-b border-border space-y-1" data-testid="agency-kind-switches">
      {(Object.keys(KIND_LABELS) as Kind[]).map((k) => (
        <label key={k} className="flex items-center justify-between gap-2 text-xs">
          <span>{KIND_LABELS[k]}</span>
          <input
            type="checkbox"
            checked={current[k] !== false}
            disabled={!blob.loaded || blob.save.saving}
            onChange={(e) => blob.commit({ notifications: { ...current, [k]: e.target.checked } })}
          />
        </label>
      ))}
      {blob.save.error && <div className="text-err text-xs">{blob.save.error}</div>}
    </div>
  );
}

function when(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
