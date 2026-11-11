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
 * click marks it read; "Mark all read" reads the rest; a row's ✕ dismisses it
 * and "Clear all" dismisses every row up to the newest one shown (gone from the
 * list; the server keeps them for the dedupe, so a sweep does not file them
 * again; one filed after the list was read stays). The kind switches
 * (AgencyKindSwitches, in the bell's Settings tab) save the `notifications` key
 * of the preferences blob — a kind switched off is no longer filed. A row whose `data.href` names a page (a 2FA relink:
 * /creators?relink=browserbase) is a link to it; the click reads it too.
 *
 * `pinned` rows (a Creator OnlyFans wants a signed consent form from) sit on
 * top, apart from the paged ones: no read, nothing to dismiss (the relay
 * refuses it, 409); a click opens where it gets fixed (`consentFixHref`, when
 * there is one). They go when the relay clears them (the problem is solved, or
 * the Agency dropped the Creator). The shell's ConsentBanner reads them from
 * this same query.
 */

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { TriangleAlert, X } from "lucide-react";

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
interface ListResp { notifications: AgencyNotification[]; unread: number; pinned: AgencyNotification[] }

function useAgencyList(enabled: boolean) {
  return useQuery<ListResp>({
    queryKey: AGENCY_NOTIFICATIONS_KEY,
    queryFn: () => relay.get<ListResp>("/admin/agency-notifications?limit=30"),
    refetchInterval: ssePoll(300_000, 60_000),
    staleTime: 30_000,
    enabled,
  });
}

/** The list for the signed-in owner; a chatter's session reads nothing (the routes refuse it). */
function useOwnerList() {
  const { user } = useUser();
  const { chatter } = useChatter();
  const owner = !!user && !chatter;
  return { owner, q: useAgencyList(owner) };
}

/** The owner's unread count for the bell's badge and its Agency tab, or null for anyone else. */
export function useAgencyUnread(): number | null {
  const { owner, q } = useOwnerList();
  return owner ? (q.data?.unread ?? 0) : null;
}

/** The owner's pinned rows (consent forms OnlyFans wants), [] for anyone else. */
export function useAgencyPinned(): AgencyNotification[] {
  const { owner, q } = useOwnerList();
  return (owner && q.data?.pinned) || NO_ROWS;
}
const NO_ROWS: AgencyNotification[] = [];

/** The page where a pinned row's Creator gets fixed (that Creator's consent switch), else null:
 *  the pinned row links there, and so does the banner's View while only one Creator is flagged. */
export function consentFixHref(accountId: string | null): string | null {
  void accountId;   // no such page here: the rows stay plain and View opens the bell
  return null;
}

/** A pinned row's Creator name (`data.name`), else its account id. */
export function pinnedName(n: AgencyNotification): string {
  const name = (n.data as { name?: unknown } | null)?.name;
  return typeof name === "string" && name ? name : (n.account_id ?? "a creator");
}

/** The Agency tab of the top bar's bell: "Mark all read", "Clear all" and
 *  the rows. Mounted only for the owner (`useAgencyUnread` not null). */
export function AgencyFeed() {
  const qc = useQueryClient();
  const q = useAgencyList(true);
  const rows = q.data?.notifications ?? [];
  const read = useMutation({
    mutationFn: (id: number | null) =>
      relay.post(id == null ? "/admin/agency-notifications/read-all" : `/admin/agency-notifications/${id}/read`),
    onSettled: () => void qc.invalidateQueries({ queryKey: AGENCY_NOTIFICATIONS_KEY }),
  });
  const dismiss = useMutation({
    // Clear all sends the newest id shown: a row filed since this list was read stays.
    mutationFn: (id: number | null) => id == null
      ? relay.post("/admin/agency-notifications/dismiss-all", { up_to_id: Math.max(...rows.map((n) => n.id)) })
      : relay.post(`/admin/agency-notifications/${id}/dismiss`),
    onSettled: () => void qc.invalidateQueries({ queryKey: AGENCY_NOTIFICATIONS_KEY }),
  });

  const unread = q.data?.unread ?? 0;
  const pinned = q.data?.pinned ?? [];
  // The server's `unread` counts the pinned rows (they stay unread, read-all skips them):
  // nothing for "Mark all read" when they are all that is.
  const readable = unread - pinned.length;

  return (
    <div className="text-sm">
      <div className="flex items-center justify-end gap-2 px-3 py-2 border-b border-border text-xs">
        <button
          type="button"
          disabled={readable <= 0 || read.isPending}
          onClick={() => read.mutate(null)}
          className="text-fg-dim hover:text-fg disabled:opacity-40"
        >
          Mark all read
        </button>
        <button
          type="button"
          disabled={rows.length === 0 || dismiss.isPending}
          onClick={() => dismiss.mutate(null)}
          className="text-fg-dim hover:text-fg disabled:opacity-40"
        >
          Clear all
        </button>
      </div>
      {q.isLoading && <div className="px-3 py-4 text-fg-dim">Loading…</div>}
      {pinned.length > 0 && (
        <ul aria-label="Needs action">
          {pinned.map((n) => {
            const fix = consentFixHref(n.account_id);
            const body = (
              <div className="flex items-start gap-2">
                <TriangleAlert aria-hidden className="mt-0.5 w-4 h-4 shrink-0 text-warn" />
                <div className="min-w-0">
                  <div className="text-sm text-fg font-medium">{n.text}</div>
                  <div className="text-[11px] text-fg-dim mt-0.5">
                    {when(n.created_at)} · clears itself once solved
                  </div>
                </div>
              </div>
            );
            return (
              <li key={n.id} data-testid="agency-pinned" className="border-b border-border/40 bg-[rgba(255,161,95,.12)]">
                {fix
                  ? <Link href={fix} className="block px-3 py-2 hover:bg-[rgba(255,161,95,.2)]">{body}</Link>
                  : <div className="px-3 py-2">{body}</div>}
              </li>
            );
          })}
        </ul>
      )}
      {!q.isLoading && rows.length === 0 && pinned.length === 0 && (
        <div className="px-3 py-6 text-center text-fg-dim">No agency notifications yet.</div>
      )}
      <ul>
        {rows.map((n) => {
          const onClick = () => { if (!n.read) read.mutate(n.id); };
          const cls = "block flex-1 min-w-0 text-left px-3 py-2";
          const body = (
            <>
              <div className={cn("text-sm", n.read ? "text-fg-dim" : "text-fg font-medium")}>{n.text}</div>
              <div className="text-[11px] text-fg-dim mt-0.5">{when(n.created_at)}</div>
            </>
          );
          const href = hrefOf(n);
          return (
            <li key={n.id} className={cn(
              "flex items-start border-b border-border/40 last:border-0 hover:bg-bg-elev-2",
              !n.read && "bg-accent/5",
            )}>
              {href
                ? <Link href={href} onClick={onClick} className={cls}>{body}</Link>
                : <button type="button" onClick={onClick} className={cls}>{body}</button>}
              <button
                type="button"
                aria-label="Dismiss"
                title="Dismiss"
                disabled={dismiss.isPending}
                onClick={() => dismiss.mutate(n.id)}
                className="shrink-0 m-1.5 w-8 h-8 sm:w-6 sm:h-6 grid place-items-center rounded text-fg-dim hover:text-fg hover:bg-bg-elev-1"
              >
                <X aria-hidden className="w-4 h-4" />
              </button>
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

/** Per-kind switches over `preferences.notifications` (absent = on): the bell's Settings tab, for the owner. */
export function AgencyKindSwitches() {
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
