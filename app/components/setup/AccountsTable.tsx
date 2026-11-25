"use client";


import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  EllipsisVertical, Link2, Pencil, Plus, Trash2, UserCheck, UserX,
  type LucideIcon,
} from "lucide-react";
import { useState, type ReactNode } from "react";

import { relay, RelayError, type AccountMeta, type Employee } from "@/lib/relay";
import { Badge, ExtraTag, Input } from "@/components/ui/primitives";
import { AccountAvatarPicture, type AvatarHealth } from "@/components/ui/AccountAvatarPicture";
import { EmptyState, HB_TABLE, HbPager } from "@/components/ui/infloww";
import { OnlyfansLine } from "@/components/shell/inflowwIcons";
import { PlatformLogo } from "@/components/shell/PlatformSwitcher";
import { fetchAccounts, type AccountsResp } from "@/hooks/useAccounts";
import { PLATFORM_NAME, accountPlatform, type Platform } from "@/lib/platform";
import { useOutsideClose } from "@/components/ui/Menu";
import { ROW_LINK_TITLE as ROW_LINK, type SectionKey } from "@/components/setup/AddCreatorModal";
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

interface HealthAllResp {
  ok: boolean;
  accounts: Array<{
    account_id: string;
    nickname?: string | null;
    ok: boolean;
    name?: string;
    profile?: AvatarHealth["profile"];
    error?: string;
    timed_out?: boolean;
    message?: string;
    upstream_body?: string;
    upstream_status?: number;
    proxy?: { label?: string | null; url?: string | null } | null;
  }>;
}
type Health = HealthAllResp["accounts"][number];

const PAGE_SIZES = [10, 20, 50] as const;

export type RowConnectivity = Connectivity & { connected: boolean };
const down = (c: Connectivity): RowConnectivity => ({ ...c, connected: false });

export function connectivity(a: AccountMeta, h: Health | undefined, read: { loaded: boolean; error: Error | null }): RowConnectivity {
  if (a.role === "watcher") {
    if (a.session_dead_at) return down({ label: "Disconnected", tone: "err", dead: true });
    return a.has_session
      ? { label: "Session captured", tone: "muted", title: "watcher account: not probed", connected: true }
      : down({ label: "—", tone: "muted", title: "no captured session" });
  }
  const fansly = a.platform === "fansly";
  const settled = sessionConnectivity(a);
  if (settled) return down(settled.dead && fansly ? { ...settled, title: FANSLY_T.rebind } : settled);
  if (read.error) return down({ label: "—", title: read.error.message, tone: "muted" });
  if (!read.loaded) return down({ label: "Pending connection", tone: "muted" });
  if (!h) return down({ label: "—", title: "no health answer for this Creator", tone: "muted" });
  if (h.ok) return { label: "Connected", tone: "ok", title: h.name, connected: true };
  // A timed-out probe is no verdict on the session: the relay stopped waiting but the OF call is still running upstream.
  if (h.timed_out) return down({ label: "Pending connection", title: h.message, tone: "muted" });
  if (h.error === "no_session") return down({ label: "Not connected", tone: "muted" });
  return down({ label: "Disconnected", tone: "err", title: fansly ? FANSLY_T.rebind : h.error || "down" });
}

interface RowCells {
  account: AccountMeta;
  conn: RowConnectivity;
  isDefault: boolean;
  employees: ReactNode;
  name: ReactNode;
  tag: ReactNode;
  actions: ReactNode;
}

const COLUMNS: ReadonlyArray<{
  key: string; head: ReactNode; width: number; title?: string; sticky?: boolean; cell: (c: RowCells) => ReactNode;
}> = [
  { key: "creators-manage#29", head: "", width: 56, cell: () => null },
  { key: "creators-manage#30", head: "Creator", width: 180, cell: (c) => c.name },
  {
    key: "creators-manage#32", head: "Nickname", width: 200,
    cell: (c) => (
      <span className="flex min-w-0 items-center gap-2">
        <span className="truncate">{c.account.nickname ?? ""}</span>
        {c.isDefault && <Badge color="muted" title={EXTRA_LABEL}>default</Badge>}
        {!c.account.is_active && <Badge color="muted">Deactivated</Badge>}
      </span>
    ),
  },
  {
    key: "creators-manage#34", width: 160, cell: (c) => c.tag,
    head: (
      <span className="flex items-center justify-between">
        Tag
        <TagSettings />
      </span>
    ),
  },
  {
    key: "creators-manage#36", head: "Account", width: 180,
    cell: (c) => <AccountCell platform={accountPlatform(c.account)} />,
  },
  { key: "creators-manage#37", head: "Creator ID", width: 160, cell: (c) => <CreatorIdCell account={c.account} /> },
  { key: "creators-manage#38", head: "Employees", width: 160, cell: (c) => c.employees },
  { key: "creators-manage#39", head: "Connectivity status", width: 190, cell: (c) => <ConnectivityCell account={c.account} conn={c.conn} /> },
  { key: "creators-manage#43", head: "Action", width: 104, sticky: true, cell: (c) => c.actions },
];

function AccountCell({ platform }: { platform: Platform }) {
  return (
    <span className="flex items-center gap-1.5 whitespace-nowrap">
      {platform === "fansly"
        ? <PlatformLogo platform="fansly" className="h-3.5 w-3.5" />
        : <OnlyfansLine aria-hidden className="h-3.5 w-3.5 shrink-0" />}
      {PLATFORM_NAME[platform]}
    </span>
  );
}

function CreatorIdCell({ account }: { account: AccountMeta }) {
  return <span className="block truncate tabular-nums">{account.id}</span>;
}

const SCROLL = cn(
  "overflow-x-auto [scrollbar-color:#666_transparent]",
  "[&::-webkit-scrollbar]:h-2 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-[#666]",
  "[&::-webkit-scrollbar-track]:bg-transparent",
);

export type AddFrom = { draft: DraftCreator } | { linkAnother: { creator: CreatorDetails; linked: Platform[] } };

type Deleting =
  | { kind: "account"; id: string; creator: string; nickname?: string; watcher?: boolean }
  | { kind: "draft"; id: string; creator: string };

export default function AccountsTable({ onLink, onAdd, children }: {
  onLink?: (at: SectionKey, expectedAccountId?: string) => void;
  onAdd?: (from: AddFrom) => void;
  children?: ReactNode;
} = {}) {
  const qc = useQueryClient();
  const profiles = useCreatorProfiles();
  const [deleting, setDeleting] = useState<Deleting | null>(null);
  const [toggling, setToggling] = useState<{ id: string; creator: string; active: boolean } | null>(null);
  const [editing, setEditing] = useState<{ account: AccountMeta; conn: string } | { draft: DraftCreator } | null>(null);
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
  });

  const proxiesQ = useProxyList();

  const employeesQ = useQuery<{ employees: Employee[] }>({
    queryKey: ["employees", "active"],
    queryFn: () => relay.get<{ employees: Employee[] }>("/admin/employees?include_disabled=false"),
    staleTime: 10_000,
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
  const proxyError = proxiesQ.error
    ? proxiesQ.error instanceof RelayError && proxiesQ.error.status === 403 ? NOT_WIRED : proxiesQ.error.message
    : null;
  const proxyOf = (id: string): string | null => {
    if (proxyError) return `Custom proxy: ${proxyError}`;
    if (proxiesQ.data?.pool?.account_ids.includes(id)) return INFLOWWWW_PROXY;
    const label = proxyByAid.get(id);
    return label ? `Custom proxy · ${label}` : null;
  };

  const roster = employeesQ.error ? null : (employeesQ.data?.employees ?? []).filter((e) => !!e.chatter_id);
  const employeesOf = (id: string): ReactNode => {
    if (!roster) return <span aria-disabled="true" title={NOT_WIRED} className="opacity-50">—</span>;
    const names = roster.filter((e) => e.account_ids == null || e.account_ids.includes(id)).map((e) => e.display_name);
    return <span title={names.join(", ")} className="line-clamp-2">{names.join(", ")}</span>;
  };
  const connWired = !healthQ.error;
  const rowFilter = { filters, connWired, picked: roster?.find((e) => String(e.id) === filters.employee) };
  const keep = (a: AccountMeta) => keepAccount({
    id: a.id,
    names: [a.nickname, a.name, a.id, profiles.profiles[a.id]?.name],
    platform: a.platform,
    tag: profiles.profiles[a.id]?.tag,
    isActive: a.is_active,
    conn: () => connectivity(a, healthByAid.get(a.id), healthRead).label,
  }, rowFilter);
  const accounts = (accountsQ.data?.accounts || []).filter(keep);
  const drafts = accountsQ.data ? [...profiles.drafts].reverse().filter((d) => keepDraft(d.name, rowFilter)) : [];
  const watchers = (accountsQ.data?.watchers ?? []).filter(keep);
  type Item = { kind: "draft"; d: DraftCreator } | { kind: "account"; a: AccountMeta };
  const all: Item[] = [
    ...drafts.map((d) => ({ kind: "draft" as const, d })),
    ...[...accounts, ...watchers].map((a) => ({ kind: "account" as const, a })),
  ];
  const total = all.length;
  const { current, shown } = usePagedRows(all, pageSize, { page, clamp });

  const scroll = shown.length > 0;
  const message = (body: ReactNode) => (
    <tr><td colSpan={COLUMNS.length} className="px-[18px] text-center max-md:text-left text-fg-dim">{body}</td></tr>
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 px-4 pt-4 md:overflow-y-auto">
        <CreatorFilterBar
          value={filters} onChange={set} employees={roster} connWired={connWired}
          tags={profiles.wired ? profiles.tags : null}
        />
        <div className={cn("mt-6", SCROLL)}>
          <table className={HB_TABLE.table}>
            <thead>
              <tr>
                {COLUMNS.map((c) => (
                  <th key={c.key} title={c.title} style={scroll ? { width: c.width } : undefined} className={cn(HB_TABLE.th, c.sticky && STICKY)}>
                    {c.head}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {accountsQ.isLoading && <SkeletonRows cols={COLUMNS.length} cellClassName={HB_TABLE.td} />}
              {accountsQ.error && message(<div className="h-12 leading-[48px] text-err" title={EXTRA_LABEL}>{(accountsQ.error as Error).message}</div>)}
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
                    avatarHealth={a.role === "watcher" ? undefined : {
                      profile: healthByAid.get(a.id)?.ok ? healthByAid.get(a.id)?.profile : undefined,
                      settled: healthQ.isSuccess || healthQ.isError,
                    }}
                    conn={conn}
                    proxy={proxyOf(a.id)}
                    employees={employeesOf(a.id)}
                    onLink={onLink}
                    onEdit={() => setEditing({ account: a, conn: conn.label })}
                    onLinkAnother={onAdd && (() => onAdd({
                      linkAnother: {
                        creator: { name: profile?.name || a.nickname || "", gender: profile?.gender ?? "", avatar: profile?.avatar },
                        linked: [accountPlatform(a)],
                      },
                    }))}
                    isDefault={accountsQ.data?.active_account_id === a.id}
                    onRename={(nickname) => renameM.mutate({ id: a.id, nickname })}
                    onActivate={() => activateM.mutate(a.id)}
                    onToggleActive={() => setToggling({ id: a.id, creator, active: !a.is_active })}
                    onDelete={() => setDeleting({
                      kind: "account", id: a.id, creator,
                      nickname: profile?.name && a.nickname && a.nickname !== profile.name ? a.nickname : undefined,
                      watcher: a.role === "watcher",
                    })}
                  />
                );
              })}
            </tbody>
          </table>
        </div>
        {children && <div className="space-y-6 py-6">{children}</div>}
      </div>

      {deleting && (
        <DeleteCreatorModal
          creator={deleting.creator}
          nickname={deleting.kind === "account" ? deleting.nickname : undefined}
          watcher={deleting.kind === "account" && deleting.watcher}
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

      {total > 0 && (
        <HbPager
          className="mx-4 shrink-0"
          total={total} count={total - watchers.length} page={current} size={pageSize} sizes={[...PAGE_SIZES]}
          noun={watchers.length ? `creators + ${watchers.length} watcher${watchers.length > 1 ? "s" : ""}` : "creators"}
          onPage={setPage} onSize={(pageSize) => set({ pageSize })}
        />
      )}
    </div>
  );
}

const PROXY_DOWN_TITLE = `${EXTRA_LABEL}\nThe proxy this Creator leaves through is unreachable; the relay rechecks it. ` +
  "On the Inflowwww proxy the Creator is moved to a healthy one after two failed rechecks; on a custom proxy, or with " +
  "no healthy Inflowwww proxy left, it stays here until the proxy answers again (Creators › Custom proxy to change it).";

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
          {account.proxy_bad_reason === "flapping" ? "proxy refusing" : "proxy unreachable"}
        </Badge>
      )}
    </span>
  );
}

function Row({
  account,
  profile,
  avatarHealth,
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
  profile?: CreatorProfile;
  avatarHealth?: AvatarHealth;
  conn: RowConnectivity;
  proxy: string | null;
  employees: ReactNode;
  isDefault: boolean;
  onLink?: (at: SectionKey, expectedAccountId?: string) => void;
  onEdit: () => void;
  onLinkAnother?: () => void;
  onRename: (n: string) => void;
  onActivate: () => void;
  onToggleActive: () => void;
  onDelete: () => void;
}) {
  const fansly = account.platform === "fansly";
  const watcher = account.role === "watcher";
  const onLink = onLinkAt && fansly ? () => onLinkAt("fansly", account.id) : onLinkAt;
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
  const extras = [
    EXTRA_LABEL, account.id, proxy, account.last_used_at && `Last used ${fmtRelTime(account.last_used_at)}`,
  ].filter(Boolean).join("\n");
  const name = (
    <div className="flex items-center gap-3" title={extras}>
      {profile?.avatar
        ? <img src={profile.avatar} alt="" aria-hidden className="h-6 w-6 shrink-0 rounded-full object-cover" />
        : accountPlatform(account) === "onlyfans"
          ? (
            <span className="h-6 w-6 shrink-0 overflow-hidden rounded-full" aria-hidden>
              <AccountAvatarPicture account={{ ...account, color: account.color || "#888" }} letters={0} initialClassName="" health={avatarHealth} />
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
      {watcher && <Badge color="muted" title="Watcher account: reads what your Creators send; not a Creator">watcher</Badge>}
    </div>
  );
  const tag = profile?.tag ? <Badge color="muted">{profile.tag}</Badge> : null;

  const { connected } = conn;
  const caps: RowCaps = {
    edit: !connected, recovery: !connected && !fansly,
    linkAnother: !watcher, toggleActive: !watcher, makeDefault: !isDefault && !watcher,
  };
  const actions = (
    <>
      <div className="flex items-center gap-2">
        {connected ? (
          <button type="button" aria-label="Edit" title="Edit" onClick={onEdit} className={ACT}>
            <Pencil className="h-4 w-4" aria-hidden />
          </button>
        ) : (
          <button
            type="button" aria-label={ROW_LINK} title={ROW_LINK}
            onClick={() => onLink?.("browserbase")}
            className={ACT}
          >
            <Link2 className="h-4 w-4" aria-hidden />
          </button>
        )}
        <RowMenu
          label={label}
          caps={caps}
          onLink={onLink}
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
    <tr className={HB_TABLE.row} data-testid={watcher ? "accounts-watcher-row" : undefined}>
      {COLUMNS.map((c) => (
        <td key={c.key} className={cn(HB_TABLE.td, c.sticky && STICKY)}>{c.cell(cells)}</td>
      ))}
    </tr>
  );
}

interface RowCaps { edit: boolean; recovery: boolean; linkAnother: boolean; toggleActive: boolean; makeDefault: boolean }

function RowMenu({
  label, caps, onLink, onEdit, onLinkAnother, onDelete, onRename, onActivate, active, onToggleActive,
}: {
  label: string;
  caps: RowCaps;
  onLink?: (at: SectionKey) => void;
  onEdit: () => void;
  onLinkAnother?: () => void;
  onDelete: () => void;
  onRename: () => void;
  onActivate: () => void;
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
          {caps.edit && item("Edit", onEdit, { icon: Pencil })}
          {caps.linkAnother && item("Link another account", onLinkAnother, { icon: Plus })}
          {caps.toggleActive && (active
            ? item("Deactivate", onToggleActive, { icon: UserX })
            : item("Activate", onToggleActive, { icon: UserCheck }))}
          {item("Delete", onDelete, { danger: true, icon: Trash2 })}
          {caps.recovery && (
            <div role="group" aria-label="Recovery" className={MENU_RULE}>
              {item("Log in to account via OnlyFans", onLink && (() => onLink("browserbase")))}
              {item("Log in to account via Login+")}
            </div>
          )}
          <div role="group" aria-label={EXTRA_LABEL} className={MENU_RULE}>
            <div className="px-3 py-1"><ExtraTag /></div>
            {item("Rename", onRename, { title: EXTRA_LABEL })}
            {caps.makeDefault && item("Make default", onActivate, { title: EXTRA_LABEL })}
          </div>
        </div>
      )}
    </div>
  );
}
