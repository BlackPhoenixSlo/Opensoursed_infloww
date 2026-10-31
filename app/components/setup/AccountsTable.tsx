"use client";

/**
 * AccountsTable — the creator table of Creators › Manage creators, drawn as the
 * Layout capture draws it (docs/infloww-layouts/creators-manage.md): its
 * filter bar (CreatorFilterBar) narrowing the rows, the capture's columns in
 * its order, its connectivity labels, and its footer ("Total: N creators",
 * "Per page") paging the rows on the client. One row per OF model account the
 * relay knows about. Each row's Action cell holds the capture's row button and
 * its "⋮" menu (creators-manage#45 to #48): the capture's items, its recovery
 * actions (which open the Add creator modal through `onLink`), then our extras.
 *
 * Powered by (no Relay route of its own; the spec's reads for /creators):
 *   GET  /admin/accounts            list + active
 *   GET  /health?all_accounts=1     per-account live OF probe
 *   GET  /admin/proxies             the bound proxy, under PasteCurlCard's key
 *   GET  /admin/employees           the Employee filter, by Creator access
 *   PATCH /admin/accounts/{id}      rename / recolor
 *   POST /admin/accounts/active     mark as default
 *   POST /admin/accounts/{id}/active  deactivate / activate (its pollers and automations stop; the row stays)
 *   DELETE /admin/accounts/{id}     remove (soft on disk; sessions kept)
 *   GET/PUT /admin/settings/account  the `creators` profile (useCreatorProfiles): each account's Creator name,
 *                                   image, Tag, and the Creators saved with Done ("Pending connection" rows)
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  EllipsisVertical, Link2, Pencil, Plus, Trash2, UserCheck, UserX,
  type LucideIcon,
} from "lucide-react";
import { useState, type ReactNode } from "react";

import { relay, RelayError, type AccountMeta, type Employee } from "@/lib/relay";
import { Badge, ExtraTag, Input } from "@/components/ui/primitives";
import { AccountAvatarPicture } from "@/components/ui/AccountAvatarPicture";
import { EmptyState, HB_TABLE, HbPager } from "@/components/ui/infloww";
import { OnlyfansLine } from "@/components/shell/inflowwIcons";
import { PlatformLogo } from "@/components/shell/PlatformSwitcher";
import { useAccountAvatar } from "@/hooks/useAccountAvatar";
import { fetchAccounts } from "@/hooks/useAccounts";
import { useOutsideClose } from "@/components/ui/Menu";
// The capture's row title, `creators0174` (creators-manage#46, #56), shared with the modal it opens.
import { ROW_LINK_TITLE as ROW_LINK, type SectionKey } from "@/components/setup/AddCreatorModal";
import type { Platform } from "@/components/setup/addCreatorWizard";
import { EditAccountModal, EditDraftModal } from "@/components/setup/EditCreatorModal";
import { FANSLY_T } from "@/components/setup/FanslyPasteSessionCard";
import { CreatorToaster, INFLOWWWW_PROXY, T, toast, useProxyList } from "@/components/setup/creatorFlow";
import {
  ACT, ActiveCreatorModal, DeleteCreatorModal, DraftRow, MENU_BOX, MENU_OFF, MENU_ON, MENU_ROW, MENU_RULE, NOT_WIRED,
  STICKY,
} from "@/components/setup/AccountsTableModals";
import { useCreatorProfiles, type CreatorDetails, type CreatorProfile, type DraftCreator } from "@/lib/creatorProfiles";
import CreatorFilterBar, { NO_FILTERS, type CreatorFilters } from "@/components/setup/CreatorFilterBar";
import { usePagedFilters, usePagedRows } from "@/hooks/pagedFilters";
import { keepAccount, keepDraft } from "@/components/setup/creatorRowFilter";
import TagSettings from "@/components/setup/TagSettings";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import { cn, describeDeadSession, fmtRelTime } from "@/lib/utils";
import { sessionConnectivity, type Connectivity } from "@/lib/sessionConnectivity";
import { SkeletonRows } from "@/components/ui/Skeleton";

interface AccountsResp {
  accounts: AccountMeta[];
  active_account_id: string | null;
}
interface HealthAllResp {
  ok: boolean;
  accounts: Array<{
    account_id: string;
    nickname?: string | null;
    ok: boolean;
    name?: string;
    error?: string;
    timed_out?: boolean;
    message?: string;
    upstream_body?: string;
    upstream_status?: number;
    proxy?: { label?: string | null; url?: string | null } | null;
  }>;
}
type Health = HealthAllResp["accounts"][number];

/** The bundle's `pageSizeOptions:["10","20","50"]` and `defaultPageSize:10` (creators-manage#52; rung 1, observed at
 *  index.9f50f370.js @12511056 and @12511016). The ticket's 10 / 25 / 50 is the Inventory's list, which the
 *  capture's Notes record as disagreeing with the bundle. */
const PAGE_SIZES = [10, 20, 50] as const;
/** Platform names (creators-manage#20). */
const PLATFORM_LABEL = { onlyfans: "OnlyFans", fansly: "Fansly" } as const;

/**
 * The one connectivity mapping (spec phase-04, Implementation Decisions,
 * Connectivity mapping), in the capture's words (creators-manage#23, #40): the
 * accounts read's verdict (lib/sessionConnectivity, shared with the KPI cards)
 * outranks the live probe, which decides only a live session.
 */
export function connectivity(a: AccountMeta, h: Health | undefined, read: { loaded: boolean; error: Error | null }): Connectivity {
  // A Fansly session the relay can no longer use reads Infloww's fansly0003 (FANSLY_T.rebind).
  const fansly = a.platform === "fansly";
  // From the accounts read, so a failed health read cannot hide it.
  const settled = sessionConnectivity(a);
  if (settled) return settled.dead && fansly ? { ...settled, title: FANSLY_T.rebind } : settled;
  // ASSUMPTION: "—" is ours; no capture label means "we could not ask" (spec, Further Notes, rung 5). Overturned by a
  // capture label for an unknown state.
  if (read.error) return { label: "—", title: read.error.message, tone: "muted" };
  if (!read.loaded) return { label: "Pending connection", tone: "muted" };
  // ASSUMPTION: a loaded answer that lacks the row is "—", not "Pending connection": nothing is still probing, and the
  // relay answers one row per account (`_health_all_accounts`), so this only shows a relay fault (rung 5). Overturned
  // if the relay starts answering partial snapshots that a later read completes.
  if (!h) return { label: "—", title: "no health answer for this Creator", tone: "muted" };
  if (h.ok) return { label: "Connected", tone: "ok", title: h.name };
  // A probe that outran the relay's budget is NOT a verdict on the session: the relay stopped waiting, it did not
  // cancel, and the OF call is still running upstream.
  if (h.timed_out) return { label: "Pending connection", title: h.message, tone: "muted" };
  if (h.error === "no_session") return { label: "Not connected", tone: "muted" };
  return { label: "Disconnected", tone: "err", title: fansly ? FANSLY_T.rebind : h.error || "down" };
}

/** Everything one row's cells read. */
interface RowCells {
  account: AccountMeta;
  conn: Connectivity;
  isDefault: boolean;
  employees: ReactNode;
  name: ReactNode;
  tag: ReactNode;
  actions: ReactNode;
}

/** The columns, in the capture's order (creators-manage#29 to #43), each with its own renderer. */
const COLUMNS: ReadonlyArray<{
  key: string; head: ReactNode; width: number; title?: string; sticky?: boolean; cell: (c: RowCells) => ReactNode;
}> = [
  { key: "creators-manage#29", head: "", width: 56, cell: () => null },
  // The Relay has no Creator above its accounts: Creator shows the account's stored Creator name (the Add creator
  // flow's, useCreatorProfiles), else its nickname, else its id; Nickname the stored nickname alone.
  { key: "creators-manage#30", head: "Creator", width: 180, cell: (c) => c.name },
  {
    key: "creators-manage#32", head: "Nickname", width: 200,
    // Our default Creator's badge follows the nickname (an extra; the capture has none).
    cell: (c) => (
      <span className="flex min-w-0 items-center gap-2">
        <span className="truncate">{c.account.nickname ?? ""}</span>
        {c.isDefault && <Badge color="muted" title={EXTRA_LABEL}>default</Badge>}
        {/* A deactivated creator's chip (creators-manage#32, `employee0042`). */}
        {!c.account.is_active && <Badge color="muted">Deactivated</Badge>}
      </span>
    ),
  },
  {
    key: "creators-manage#34", width: 160, cell: (c) => c.tag,
    head: (
      <span className="flex items-center justify-between">
        Tag
        {/* creators-manage#35: the Tag manager (rename, delete, "used by N"); a new Tag is typed in the account details. */}
        <TagSettings />
      </span>
    ),
  },
  {
    key: "creators-manage#36", head: "Account", width: 180,
    cell: (c) => <AccountCell platform={c.account.platform ?? "onlyfans"} />,
  },
  { key: "creators-manage#37", head: "Creator ID", width: 160, cell: (c) => <CreatorIdCell account={c.account} /> },
  { key: "creators-manage#38", head: "Employees", width: 160, cell: (c) => c.employees },
  { key: "creators-manage#39", head: "Connectivity status", width: 190, cell: (c) => <ConnectivityCell account={c.account} conn={c.conn} /> },
  // `fixed:"right"` (creators-manage#43): it stays in view while the table scrolls sideways, on #171717 with a 1px
  // #2c2c2c rule at its left (01-home.png).
  // ASSUMPTION: fixed from 768px up only, as the Tracking links table fixes its Actions (`md:sticky`), since a phone
  // has no room to spare beside a pinned column (rung 3). Overturned by a 390px render of the bundle.
  { key: "creators-manage#43", head: "Action", width: 104, sticky: true, cell: (c) => c.actions },
];

/** The Account cell (01-home.png): the platform's 14px mark 6px before its name. OnlyFans takes Infloww's white line
 *  mark (the shell's `OnlyfansLine`); Fansly, which has no line mark on disk, its brand mark. */
function AccountCell({ platform }: { platform: Platform }) {
  return (
    <span className="flex items-center gap-1.5 whitespace-nowrap">
      {platform === "fansly"
        ? <PlatformLogo platform="fansly" className="h-3.5 w-3.5" />
        : <OnlyfansLine aria-hidden className="h-3.5 w-3.5 shrink-0" />}
      {PLATFORM_LABEL[platform]}
    </span>
  );
}

/** Creator ID (creators-manage#37; 01-home.png's "@founder"): the account's `@username`, from the `/users/me` read
 *  the avatar already makes (useAccountAvatar, one cache entry), so no new read. A Fansly row is never asked (as its
 *  avatar is not), and its cell stays empty. */
function CreatorIdCell({ account }: { account: AccountMeta }) {
  const of = (account.platform ?? "onlyfans") === "onlyfans";
  const username = useAccountAvatar(of ? account.id : null).data?.username;
  return username ? <span className="block truncate">@{username}</span> : null;
}

/** HB's horizontal scrollbar under the rows (01-home.png): an 8px rounded #666 thumb on no track. */
const SCROLL = cn(
  "overflow-x-auto [scrollbar-color:#666_transparent]",
  "[&::-webkit-scrollbar]:h-2 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-[#666]",
  "[&::-webkit-scrollbar-track]:bg-transparent",
);

/** What a row's Link creator account / Link another account opens the Add creator modal with. */
export type AddFrom = { draft: DraftCreator } | { linkAnother: { creator: CreatorDetails; linked: Platform[] } };

/** What the Delete modal deletes: an account, or a Creator saved with Done. */
type Deleting =
  | { kind: "account"; id: string; creator: string; nickname?: string }
  | { kind: "draft"; id: string; creator: string };

export default function AccountsTable({ onLink, onAdd, children }: {
  /** Opens the page's Add creator modal at the section that performs a row's recovery action. */
  onLink?: (at: SectionKey) => void;
  /** Opens the page's Add creator modal at select-platform: a Creator with no account, or Link another account. */
  onAdd?: (from: AddFrom) => void;
  /** The page's extras, drawn after the table and above the footer, which keeps the page's foot. */
  children?: ReactNode;
} = {}) {
  const qc = useQueryClient();
  const profiles = useCreatorProfiles();
  // The Creator the Delete modal asks about (creators-manage#78); null: closed.
  const [deleting, setDeleting] = useState<Deleting | null>(null);
  // The Creator the Deactivate / Activate modal asks about (creators-manage#77); null: closed.
  const [toggling, setToggling] = useState<{ id: string; creator: string; active: boolean } | null>(null);
  // The edit modal's subject (UpdateCreator / EditCreators); null: closed.
  const [editing, setEditing] = useState<{ account: AccountMeta; conn: string } | { draft: DraftCreator } | null>(null);
  // A filter or page-size change goes back to page 1 (usePagedFilters).
  const { page, pageSize, set, setPage, clamp, ...filters } =
    usePagedFilters<CreatorFilters & { pageSize: number }>({ ...NO_FILTERS, pageSize: PAGE_SIZES[0] });

  const accountsQ = useQuery<AccountsResp>({
    queryKey: ["accounts"],
    queryFn: fetchAccounts,
    staleTime: 30_000,
  });

  const healthQ = useQuery<HealthAllResp>({
    queryKey: ["health-all"],
    queryFn: () => relay.get<HealthAllResp>("/health?all_accounts=1"),
    staleTime: 60_000,
    // Still a live OF round-trip per account (bounded + budgeted server-side,
    // see server.py's `_health_all_accounts`), so keep the table responsive by
    // showing accountsQ data first and overlaying health when it lands.
  });

  // The same key PasteCurlCard reads, so /creators reads the proxies once (spec phase-04, Contracts).
  const proxiesQ = useProxyList();

  // The Employee filter's options and their Creator access (spec phase-04, story 11), under useRoster's own key for
  // the active roster, so the two share one cache entry.
  // ASSUMPTION: read here, not through useRoster, because useRoster waits for an owner's /auth/me and never asks for a
  // chatter, whose refusal the filter must show as Not wired (spec, Chatter sessions); the table also renders outside
  // a UserProvider in its own test (rung 5). Overturned if useRoster grows a chatter-aware mode.
  const employeesQ = useQuery<{ employees: Employee[] }>({
    queryKey: ["employees", "active"],
    queryFn: () => relay.get<{ employees: Employee[] }>("/admin/employees?include_disabled=false"),
    staleTime: 10_000,
    // A refusal (a chatter: 403) never becomes a 200 by asking again.
    retry: (n, err) => n < 2 && !(err instanceof RelayError && err.status < 500),
  });

  const renameM = useMutation({
    mutationFn: ({ id, nickname }: { id: string; nickname: string }) =>
      relay.patch<unknown>(`/admin/accounts/${encodeURIComponent(id)}`, { nickname }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["accounts"] }),
  });

  const activateM = useMutation({
    mutationFn: (account_id: string) =>
      relay.post<unknown>("/admin/accounts/active", { account_id }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["accounts"] }),
  });

  const activeM = useMutation({
    mutationFn: ({ id, active }: { id: string; active: boolean }) =>
      relay.post<unknown>(`/admin/accounts/${encodeURIComponent(id)}/active`, { active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["accounts"] }),
  });

  const deleteM = useMutation({
    mutationFn: (id: string) =>
      relay.delete<unknown>(`/admin/accounts/${encodeURIComponent(id)}`),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: ["accounts"] });
      // Hard-EVICT every per-account cache for the dropped model so a manual
      // logout/login is no longer needed to clear it. Per-account query keys
      // embed the accountId somewhere in the key — ["chats", kind, accountId,
      // ...], ["vault-media", accountId], ["of-user", accountId, fanId],
      // ["fan", accountId, ...], *-config / *-rules / automation-* / nudge-*,
      // etc. A predicate scan over the live cache removes them all without a
      // hand-maintained prefix list. removeQueries (not invalidate) drops them
      // from memory, which also evicts the persisted localStorage snapshot
      // since the persister only dehydrates live queries. The split(",") check
      // also matches the unified ("all" scope) chat key, whose accountKey is a
      // comma-joined list of every fanned-out account id (useChatList.ts).
      qc.removeQueries({
        predicate: (q) =>
          q.queryKey.some(
            (part) =>
              typeof part === "string" &&
              (part === id || part.split(",").includes(id)),
          ),
      });
    },
  });

  const healthByAid = new Map(
    (healthQ.data?.accounts || []).map((h) => [h.account_id, h]),
  );
  const healthRead = { loaded: !!healthQ.data, error: healthQ.error };
  const proxyByAid = new Map<string, string>();
  for (const p of proxiesQ.data?.proxies || []) {
    for (const id of p.assigned_account_ids || []) proxyByAid.set(id, p.label);
  }
  // A refused read (a chatter on GET /admin/proxies) is Not wired, never an error banner (spec, Chatter sessions).
  const proxyError = proxiesQ.error
    ? proxiesQ.error instanceof RelayError && proxiesQ.error.status === 403 ? NOT_WIRED : proxiesQ.error.message
    : null;
  // The bound proxy, one line for the Creator cell's title (an extra; the capture has no proxy column).
  const proxyOf = (id: string): string | null => {
    if (proxyError) return `Custom proxy: ${proxyError}`;
    if (proxiesQ.data?.pool?.account_ids.includes(id)) return INFLOWWWW_PROXY;
    const label = proxyByAid.get(id);
    return label ? `Custom proxy · ${label}` : null;
  };

  // The filters, each on what its row shows. A filter whose read failed is Not wired and applies nothing.
  // The Employees are the rows with their own login; the names on the owner's login are not (useRoster agrees).
  const roster = employeesQ.error ? null : (employeesQ.data?.employees ?? []).filter((e) => !!e.chatter_id);
  // The Employees column (creators-manage#38, names joined ", "), from the same read: each Employee whose Creator
  // access holds the row, or is null, which grants every Creator (`_creator_access`, service/employees.py).
  const employeesOf = (id: string): ReactNode => {
    if (!roster) return <span aria-disabled="true" title={NOT_WIRED} className="opacity-50">—</span>;
    const names = roster.filter((e) => e.account_ids == null || e.account_ids.includes(id)).map((e) => e.display_name);
    // Two lines, the full list on hover (creators-manage#38's `-webkit-line-clamp:2` and its HBPopover), so the cell
    // wraps between names instead of widening the table.
    return <span title={names.join(", ")} className="line-clamp-2">{names.join(", ")}</span>;
  };
  const connWired = !healthQ.error;
  const rowFilter = { filters, connWired, picked: roster?.find((e) => String(e.id) === filters.employee) };
  const accounts = (accountsQ.data?.accounts || []).filter((a) => keepAccount({
    id: a.id,
    names: [a.nickname, a.id, profiles.profiles[a.id]?.name],
    platform: a.platform,
    tag: profiles.profiles[a.id]?.tag,
    isActive: a.is_active,
    conn: () => connectivity(a, healthByAid.get(a.id), healthRead).label,
  }, rowFilter));
  // The Creators saved with Done (creatorRowFilter's keepDraft), first, newest first, as Infloww lists a new Creator
  // at the top.
  const drafts = accountsQ.data ? [...profiles.drafts].reverse().filter((d) => keepDraft(d.name, rowFilter)) : [];
  type Item = { kind: "draft"; d: DraftCreator } | { kind: "account"; a: AccountMeta };
  const all: Item[] = [
    ...drafts.map((d) => ({ kind: "draft" as const, d })),
    ...accounts.map((a) => ({ kind: "account" as const, a })),
  ];
  const total = all.length;
  // A list that shrinks under the page lands on its last page and stays there when it grows again (usePagedRows).
  const { current, shown } = usePagedRows(all, pageSize, { page, clamp });

  // The columns take their widths only while there are rows (`scroll:Cn?.items?.length>0?{x:1100}:null`,
  // creators-manage#27): empty, loading or failed, the table is no wider than its heads need, and the message row sits
  // centred, as vendor antd centres its empty row (`textAlign:"center"` on the `-placeholder` row,
  // vendor.bab480ce.js @1353522).
  // ASSUMPTION: below 768px the message sits at the left, because the heads still run past a phone's width and the
  // centre of the scrolling table is off screen (rung 5). Overturned by a 390px render of the bundle.
  const scroll = shown.length > 0;
  const message = (body: ReactNode) => (
    <tr><td colSpan={COLUMNS.length} className="px-[18px] text-center max-md:text-left text-fg-dim">{body}</td></tr>
  );

  return (
    // The bundle's `_content-wrap` (creators-manage#53's box): a full-height column whose `_layout-wrap` (16px padding,
    // none at the bottom, #12) scrolls above the footer, so the footer keeps the page's foot. From 768px up only; on a
    // phone the page scrolls as one, the footer last (the phone layout is ours).
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 px-4 pt-4 md:overflow-y-auto">
        <CreatorFilterBar
          value={filters} onChange={set} employees={roster} connWired={connWired}
          tags={profiles.wired ? profiles.tags : null}
        />
        {/* 24px below the filters (creators-manage#28). The wrapper scrolls sideways at every row count, so an empty
            table's column heads never widen the page past a phone.
            ASSUMPTION: a column's width is its preferred width, not a floor. Where the row is narrower than their sum
            (1390px for the capture's nine, 1590px with ours, against 1156px at a 1440px window), the browser shrinks
            each column toward its content, so the table fits and no column waits behind the fixed Action column; it
            scrolls only once the cells' own content outruns the row, as on a phone (rung 5). Overturned by a render of
            the bundle at 1440px. */}
        <div className={cn("mt-6", SCROLL)}>
          <table className={HB_TABLE.table}>
            <thead>
              {/* Head cells start-aligned, as vendor antd's are (`textAlign:"start"`, vendor.bab480ce.js @1367586,
                  cited at creators-proxy#18; the browser would centre a th), 48px tall, 18px each side, weight 500
                  (creators-manage#79, #82). */}
              {/* HB's head (01-home.png): #171717, white 14px / 500, no rule under it. */}
              <tr>
                {COLUMNS.map((c) => (
                  <th key={c.key} title={c.title} style={scroll ? { width: c.width } : undefined} className={cn(HB_TABLE.th, c.sticky && STICKY)}>
                    {c.head}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {/* Loading: placeholder rows under the column heads. The bundle draws its PulserIndicator here, a
                  spinner over the faded empty body (creators-manage#51); the owner asked every page to paint its
                  layout before its data (2026-10-29), which overrides that parity, here and on Custom proxy. */}
              {accountsQ.isLoading && <SkeletonRows cols={COLUMNS.length} cellClassName={HB_TABLE.td} />}
              {/* The capture records no error line in its table (creators-manage#50, #51): ours, labelled. */}
              {accountsQ.error && message(<div className="h-12 leading-[48px] text-err" title={EXTRA_LABEL}>{(accountsQ.error as Error).message}</div>)}
              {/* antd's simple empty (creators-manage#50): the 40px art and "No data", 32px above and below. */}
              {accountsQ.data && total === 0 && message(<EmptyState size="sm" />)}
              {shown.map((it) => {
                if (it.kind === "draft") {
                  const d = it.d;
                  return (
                    <DraftRow
                      key={d.id} columns={COLUMNS} draft={d}
                      onLink={onAdd && (() => onAdd({ draft: d }))}
                      onEdit={() => setEditing({ draft: d })}
                      onDelete={() => setDeleting({ kind: "draft", id: d.id, creator: d.name })}
                    />
                  );
                }
                const a = it.a;
                const profile = profiles.profiles[a.id];
                const conn = connectivity(a, healthByAid.get(a.id), healthRead);
                const creator = profile?.name || a.nickname || a.id;
                return (
                  <Row
                    key={a.id}
                    account={a}
                    profile={profile}
                    conn={conn}
                    proxy={proxyOf(a.id)}
                    employees={employeesOf(a.id)}
                    onLink={onLink}
                    onEdit={() => setEditing({ account: a, conn: conn.label })}
                    onLinkAnother={onAdd && (() => onAdd({
                      linkAnother: {
                        creator: { name: profile?.name || a.nickname || "", gender: profile?.gender ?? "", avatar: profile?.avatar },
                        linked: [a.platform ?? "onlyfans"],
                      },
                    }))}
                    isDefault={accountsQ.data?.active_account_id === a.id}
                    onRename={(nickname) => renameM.mutate({ id: a.id, nickname })}
                    onActivate={() => activateM.mutate(a.id)}
                    onToggleActive={() => setToggling({ id: a.id, creator, active: !a.is_active })}
                    // A Creator name of its own makes the row Infloww's account under a Creator ("Creator / nickname").
                    onDelete={() => setDeleting({
                      kind: "account", id: a.id, creator,
                      nickname: profile?.name && a.nickname && a.nickname !== profile.name ? a.nickname : undefined,
                    })}
                  />
                );
              })}
            </tbody>
          </table>
        </div>
        {/* ASSUMPTION: our extras keep 24px from the table and from the footer, the capture's own gap above its table
            (#28); the capture has nothing between its table and its footer (rung 5). Overturned if the reviewer wants
            them flush. */}
        {children && <div className="space-y-6 py-6">{children}</div>}
      </div>

      {deleting && (
        <DeleteCreatorModal
          creator={deleting.creator}
          nickname={deleting.kind === "account" ? deleting.nickname : undefined}
          pending={deleteM.isPending}
          error={deleteM.error}
          onClose={() => { setDeleting(null); deleteM.reset(); }}
          onDelete={() => {
            const done = () => { toast(T.deleted(deleting.creator)); setDeleting(null); };
            if (deleting.kind === "draft") {
              profiles.removeDraft(deleting.id).then(done, (e: Error) => toast(e.message, "err"));
              return;
            }
            const id = deleting.id;
            deleteM.mutate(id, {
              onSuccess: () => {
                // The account's Creator details, Tag and notes go with it; a refused blob keeps nothing to drop.
                if (profiles.profiles[id]) void profiles.removeProfile(id).catch(() => {});
                done();
              },
            });
          }}
        />
      )}
      {toggling && (
        <ActiveCreatorModal
          creator={toggling.creator}
          activate={toggling.active}
          pending={activeM.isPending}
          error={activeM.error}
          onClose={() => { setToggling(null); activeM.reset(); }}
          onConfirm={() => activeM.mutate(
            { id: toggling.id, active: toggling.active },
            { onSuccess: () => setToggling(null) },
          )}
        />
      )}
      {editing && "account" in editing && (
        <EditAccountModal account={editing.account} conn={editing.conn} onClose={() => setEditing(null)} onLink={onLink} />
      )}
      {editing && "draft" in editing && <EditDraftModal draft={editing.draft} onClose={() => setEditing(null)} />}
      <CreatorToaster />

      {/* Shown only with a total (creators-manage#52): HB's pager footer (ticket 00's `HbPager`), the content's full width
          outside its own 16px padding (#53). */}
      {total > 0 && (
        <HbPager
          className="mx-4 shrink-0"
          total={total} noun="creators" page={current} size={pageSize} sizes={[...PAGE_SIZES]}
          onPage={setPage} onSize={(pageSize) => set({ pageSize })}
        />
      )}
    </div>
  );
}

/** `proxy_down` (service/proxy_health.py): the Creator's proxy failed DOWN_AFTER full-retry calls in a row and a
 *  probe 30 s after the first of them confirmed it; the relay rechecks it with backoff and moves a Creator on a bad
 *  Inflowwww proxy to a healthy one after two failed rechecks (docs/adr/0030). While this shows, its reads and sends
 *  still try the proxy and fail after their retries. */
const PROXY_DOWN_TITLE = `${EXTRA_LABEL}\nThe proxy this Creator leaves through is unreachable; the relay rechecks it. ` +
  "On the Inflowwww proxy the Creator is moved to a healthy one after two failed rechecks; on a custom proxy, or with " +
  "no healthy Inflowwww proxy left, it stays here until the proxy answers again (Creators › Custom proxy to change it).";

/** The capture's status text, coloured (creators-manage#41, #42), and a flagged session's repair badge. */
function ConnectivityCell({ account, conn }: { account: AccountMeta; conn: Connectivity }) {
  return (
    <span className="flex flex-wrap items-center gap-1.5">
      <span title={conn.title} className={cn(conn.tone === "ok" && "text-ok", conn.tone === "err" && "text-err")}>
        {conn.label}
      </span>
      {conn.dead && (
        <>
          <Badge color="err" title={describeDeadSession(account.session_dead_reason)}>
            automations paused
          </Badge>
          <span className="text-[11px] text-fg-dim whitespace-nowrap">
            unlinked {fmtRelTime(account.session_dead_at)}
          </span>
        </>
      )}
      {account.proxy_down && (
        <Badge color="err" title={PROXY_DOWN_TITLE}>
          proxy unreachable
        </Badge>
      )}
    </span>
  );
}

function Row({
  account,
  profile,
  conn,
  proxy,
  employees,
  isDefault,
  onLink: onLinkAt,
  onEdit,
  onLinkAnother,
  onRename,
  onActivate,
  onToggleActive,
  onDelete,
}: {
  account: AccountMeta;
  /** The account's stored Creator details, Tag and notes (useCreatorProfiles). */
  profile?: CreatorProfile;
  conn: Connectivity;
  /** The bound proxy, for the Creator cell's title. */
  proxy: string | null;
  employees: ReactNode;
  isDefault: boolean;
  onLink?: (at: SectionKey) => void;
  onEdit: () => void;
  onLinkAnother?: () => void;
  onRename: (n: string) => void;
  onActivate: () => void;
  /** Opens the Deactivate / Activate modal. */
  onToggleActive: () => void;
  onDelete: () => void;
}) {
  // A Fansly row relinks at the Fansly paste session, whichever action asks (Infloww: Fansly's own "Link account").
  const fansly = account.platform === "fansly";
  const onLink = onLinkAt && fansly ? () => onLinkAt("fansly") : onLinkAt;
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(account.nickname || account.id);

  const commitRename = () => {
    setEditing(false);
    const orig = account.nickname || account.id;
    if (draft.trim() && draft.trim() !== orig) {
      onRename(draft.trim());
    }
  };

  const label = account.nickname || account.id;
  // The Creator cell: a 24px avatar 12px before the name (creators-manage#80, #31), one line (#33). Rename, in the ⋮
  // menu, edits the nickname in place. Its title carries our extras the capture has no column for: the account id,
  // the bound proxy and when it was last used.
  const extras = [
    EXTRA_LABEL, account.id, proxy, account.last_used_at && `Last used ${fmtRelTime(account.last_used_at)}`,
  ].filter(Boolean).join("\n");
  // The avatar is the Creator's Display image (useCreatorProfiles), else (OnlyFans) the OF profile picture, else a
  // round fill in the account's colour.
  const name = (
    <div className="flex items-center gap-3" title={extras}>
      {profile?.avatar
        ? <img src={profile.avatar} alt="" aria-hidden className="h-6 w-6 shrink-0 rounded-full object-cover" />
        : (account.platform ?? "onlyfans") === "onlyfans"
          ? (
            <span className="h-6 w-6 shrink-0 overflow-hidden rounded-full" aria-hidden>
              <AccountAvatarPicture account={{ ...account, color: account.color || "#888" }} letters={0} initialClassName="" />
            </span>
          )
          : <span className="h-6 w-6 rounded-full shrink-0" style={{ background: account.color || "#888" }} aria-hidden />}
      {editing ? (
        <Input
          aria-label={`Rename ${label}`}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commitRename}
          onKeyDown={(e) => {
            if (e.key === "Enter") commitRename();
            if (e.key === "Escape") { setEditing(false); setDraft(label); }
          }}
          autoFocus
          className="w-44 py-1 text-sm"
        />
      ) : (
        <span className="truncate">{profile?.name || label}</span>
      )}
    </div>
  );
  const tag = profile?.tag ? <Badge color="muted">{profile.tag}</Badge> : null;

  // creators-manage#45, #46: a Connected row has the Edit pencil and a menu without Edit; any other row has the link
  // button and the menu with all four items.
  const connected = conn.label === "Connected";
  const actions = (
    <>
      <div className="flex items-center gap-2">
        {connected ? (
          // Edit opens "Edit account details" (UpdateCreator, EditAccountModal).
          <button type="button" aria-label="Edit" title="Edit" onClick={onEdit} className={ACT}>
            <Pencil className="h-4 w-4" aria-hidden />
          </button>
        ) : (
          // `creators0174`, "Link creator account" (#46, #58): the extension path, the owner's first way in.
          <button
            type="button" aria-label={ROW_LINK} title={ROW_LINK}
            onClick={() => onLink?.("paste")}
            className={ACT}
          >
            <Link2 className="h-4 w-4" aria-hidden />
          </button>
        )}
        <RowMenu
          label={label}
          connected={connected}
          isDefault={isDefault}
          onLink={onLink}
          fansly={fansly}
          onEdit={onEdit}
          onLinkAnother={onLinkAnother}
          onDelete={onDelete}
          onRename={() => { setDraft(label); setEditing(true); }}
          onActivate={onActivate}
          active={account.is_active}
          onToggleActive={onToggleActive}
        />
      </div>
    </>
  );

  const cells: RowCells = { account, conn, employees, isDefault, name, tag, actions };
  return (
    <tr className={HB_TABLE.row}>
      {COLUMNS.map((c) => (
        <td key={c.key} className={cn(HB_TABLE.td, c.sticky && STICKY)}>{c.cell(cells)}</td>
      ))}
    </tr>
  );
}

/**
 * The row's "⋮" menu, an overlay under the dots, right-aligned to them, above the fixed Action cell (as the Tracking
 * links row menu is). Three groups:
 *   • the capture's items in its order (creators-manage#48, RenderActions @12361331): Edit (only off a Connected row,
 *     #46), "Link another account" (the Add creator modal at select-platform, this platform taken), "Deactivate" (or
 *     "Activate" on a deactivated creator), which asks first, then "Delete", which asks first;
 *   • off a Connected row, the Inventory's recovery actions (§3.7): the OnlyFans sign-in opens the Add creator modal at
 *     Paste cURL (#59's re-link; the relay has no password sign-in, so "re-enter password" is not offered); Login+,
 *     Infloww's phone app, is Not wired;
 *   • our extras under "Inflowwww extra": Rename, Make default (not on the default Creator).
 * ASSUMPTION: "Link another account" links a new account that takes this one's Creator details; the Relay has no
 * Creator above its accounts, so the new account gets a row of its own under the same Creator name (rung 5).
 * Overturned when the Relay groups accounts under a Creator.
 * ASSUMPTION: the recovery actions sit in this menu, below the capture's items, because the capture records re-link
 * as a row entry point (#59) without placing it, and the Inventory's two labels are not in the bundle on disk (rung
 * 5). Overturned by the en locale chunk or a render of the bundle.
 */
function RowMenu({
  label, connected, fansly, isDefault, onLink, onEdit, onLinkAnother, onDelete, onRename, onActivate, active, onToggleActive,
}: {
  label: string;
  connected: boolean;
  /** Fansly: no OnlyFans recovery items; the row's link button opens the Fansly paste session. */
  fansly?: boolean;
  isDefault: boolean;
  onLink?: (at: SectionKey) => void;
  onEdit: () => void;
  onLinkAnother?: () => void;
  onDelete: () => void;
  onRename: () => void;
  onActivate: () => void;
  /** False on a deactivated creator: the item reads "Activate". */
  active: boolean;
  onToggleActive: () => void;
}) {
  const { open, setOpen, ref } = useOutsideClose();
  const [pos, setPos] = useState<{ top: number; right: number } | null>(null);

  function toggle(e: React.MouseEvent<HTMLButtonElement>) {
    const r = e.currentTarget.getBoundingClientRect();
    setPos({ top: r.bottom + 4, right: Math.max(8, window.innerWidth - r.right) });
    setOpen((o) => !o);
  }
  const item = (
    text: string, run?: () => void,
    opts: { title?: string; disabled?: boolean; danger?: boolean; icon?: LucideIcon } = {},
  ) => {
    const off = opts.disabled || !run;
    const Icon = opts.icon;
    return (
      <button
        type="button" role="menuitem" disabled={off} title={opts.title ?? (off ? NOT_WIRED : undefined)}
        onClick={() => { setOpen(false); run?.(); }}
        className={cn(
          MENU_ROW, Icon && "flex items-center gap-2",
          off ? MENU_OFF : MENU_ON, opts.danger && !off && "text-err",
        )}
      >
        {Icon && <Icon className="h-4 w-4 shrink-0" aria-hidden />}
        {text}
      </button>
    );
  };

  return (
    <div ref={ref} className="inline-flex">
      <button
        type="button" aria-label={`More actions for ${label}`} aria-haspopup="menu" aria-expanded={open}
        onClick={toggle} className={ACT}
      >
        <EllipsisVertical className="h-4 w-4" aria-hidden />
      </button>
      {open && pos && (
        <div role="menu" aria-label={`Actions for ${label}`} className={MENU_BOX} style={{ top: pos.top, right: pos.right }}>
          {/* Each capture item leads with lucide's nearest icon (#48's Edit04Line, PlusLine, UserX01Line,
              Trash01Line); the bundle's icon font is not copied. */}
          {!connected && item("Edit", onEdit, { icon: Pencil })}
          {item("Link another account", onLinkAnother, { icon: Plus })}
          {/* Opens creators-manage#77's Deactivate modal (ActiveCreatorModal). */}
          {active
            ? item("Deactivate", onToggleActive, { icon: UserX })
            : item("Activate", onToggleActive, { icon: UserCheck })}
          {/* Opens creators-manage#78's Delete modal (DeleteCreatorModal). */}
          {item("Delete", onDelete, { danger: true, icon: Trash2 })}
          {!connected && !fansly && (
            <div role="group" aria-label="Recovery" className={MENU_RULE}>
              {item("Log in to account via OnlyFans", onLink && (() => onLink("paste")))}
              {item("Log in to account via Login+")}
            </div>
          )}
          <div role="group" aria-label={EXTRA_LABEL} className={MENU_RULE}>
            <div className="px-3 py-1"><ExtraTag /></div>
            {item("Rename", onRename, { title: EXTRA_LABEL })}
            {!isDefault && item("Make default", onActivate, { title: EXTRA_LABEL })}
          </div>
        </div>
      )}
    </div>
  );
}
