"use client";


import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Plus } from "lucide-react";
import { useEffect, useState } from "react";

import { relay, type ProxyMeta, type AccountMeta } from "@/lib/relay";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import { EmptyState, IfButton, IfModal, InflowwPageHeader } from "@/components/ui/infloww";
import AddProxyModal, {
  draftLabel, type ProxyDraft,
} from "@/components/setup/AddProxyModal";
import CreatorEgressTable, {
  EMPTY_TEXT, PROXY_TABLE, proxyTh, type TestResult,
} from "@/components/setup/CreatorEgressTable";
import { SkeletonRows } from "@/components/ui/Skeleton";

interface ProxiesResp {
  proxies: Array<
    ProxyMeta & {
      assigned_accounts?: Array<{ id: string; nickname?: string | null; color?: string | null }>;
      assigned_account?: { id: string; nickname?: string | null } | null;
    }
  >;
  accounts: AccountMeta[];
}

const PAGE_SIZES = [10, 20, 50, 100] as const;
const SIZE_CHANGER_PAST = 50;

const STATUS_ON = "Available";
const STATUS_OFF = "Unavailable";

const isRefused = (err: unknown) => {
  const status = (err as { status?: unknown } | null)?.status;
  return status === 401 || status === 403;
};

export default function ProxiesTable() {
  const qc = useQueryClient();
  const [addOpen, setAddOpen] = useState(false);
  const [toast, setToast] = useState<{ ok: boolean; text: string } | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);

  const proxiesQ = useQuery<ProxiesResp>({
    queryKey: ["proxies"],
    queryFn: () => relay.get<ProxiesResp>("/admin/proxies"),
    staleTime: 60_000,
    retry: (n, err) => !isRefused(err) && n < 3,
  });
  const refused = isRefused(proxiesQ.error);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState<number>(PAGE_SIZES[0]);

  const assignM = useMutation({
    mutationFn: ({ label, account_id }: { label: string; account_id: string }) =>
      relay.post<unknown>("/admin/proxies/assign", { label, account_id }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["proxies"] });
      qc.invalidateQueries({ queryKey: ["accounts"] });
    },
  });

  const unbindM = useMutation({
    mutationFn: ({ label, account_id }: { label: string; account_id: string }) =>
      relay.post<unknown>(`/admin/proxies/${encodeURIComponent(label)}/unbind`, { account_id }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["proxies"] });
      qc.invalidateQueries({ queryKey: ["accounts"] });
    },
  });

  const testM = useMutation({
    mutationFn: (label: string) =>
      relay.post<TestResult>(
        `/admin/proxies/${encodeURIComponent(label)}/test`,
      ),
  });

  const createM = useMutation({
    mutationFn: async (body: { label: string } & Record<string, unknown>) => {
      // The Relay probes only a registered label: register, test, and unregister again when the check fails.
      await relay.post<{ ok: boolean; proxy: ProxyMeta }>("/admin/proxies", body);
      const path = `/admin/proxies/${encodeURIComponent(body.label)}`;
      const check = await relay.post<{ ok: boolean; error?: string | null }>(`${path}/test`);
      if (!check.ok) {
        await relay.delete<unknown>(path).catch(() => undefined);
        throw new Error(check.error ? `Proxy check failed: ${check.error}` : "Proxy check failed");
      }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["proxies"] });
      setAddOpen(false);
      setToast({ ok: true, text: "Proxy added" });
    },
    onError: (err: Error) => {
      qc.invalidateQueries({ queryKey: ["proxies"] });
      setToast({ ok: false, text: err.message });
    },
  });

  const removeM = useMutation({
    mutationFn: (label: string) => relay.delete<unknown>(`/admin/proxies/${encodeURIComponent(label)}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["proxies"] });
      qc.invalidateQueries({ queryKey: ["accounts"] });
      setDeleting(null);
    },
    onError: (err: Error) => {
      setToast({ ok: false, text: err.message });
      qc.invalidateQueries({ queryKey: ["proxies"] });
    },
  });

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 3000);
    return () => clearTimeout(t);
  }, [toast]);

  function submitDraft(draft: ProxyDraft) {
    setToast(null);
    createM.mutate({
      label: draftLabel(draft).trim(),
      scheme: draft.scheme,
      host: draft.host.trim(),
      port: Number(draft.port),
      username: draft.username.trim() || null,
      password: draft.password || null,
      notes: draft.notes.trim(),
    });
  }

  const proxies = proxiesQ.data?.proxies ?? [];
  const pageCount = Math.max(1, Math.ceil(proxies.length / pageSize));
  const cur = Math.min(page, pageCount);
  const shown = proxies.slice((cur - 1) * pageSize, cur * pageSize);

  return (
    <div>
      <InflowwPageHeader
        title="Manage your custom proxies"
        actions={
        <IfButton
          variant="primary"
          icon={Plus}
          className="whitespace-nowrap"
          disabled={refused}
          title={refused ? "not wired" : undefined}
          onClick={() => {
            setToast(null);
            setAddOpen(true);
          }}
        >
          Add new proxy
        </IfButton>
        }
      />

      <div className="my-6 mx-4 md:mx-10 overflow-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className={PROXY_TABLE.headRow}>
              <th className={proxyTh()}>Proxy label</th>
              <th className={proxyTh()}>Host</th>
              <th className={proxyTh()}>Port</th>
              <th className={proxyTh()}>Type</th>
              <th className={proxyTh()}>Creator</th>
              <th className={proxyTh()}>Proxy status</th>
              <th className={proxyTh(true)}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((p) => (
              <ProxyRow
                key={p.label}
                proxy={p}
                accounts={proxiesQ.data!.accounts}
                onBind={(account_id) => assignM.mutate({ label: p.label, account_id })}
                onUnbind={(account_id) => unbindM.mutate({ label: p.label, account_id })}
                onTest={() => testM.mutate(p.label)}
                onRemove={() => setDeleting(p.label)}
                testResult={testM.variables === p.label ? testM.data : undefined}
                testing={testM.isPending && testM.variables === p.label}
                removing={removeM.isPending && removeM.variables === p.label}
                busyBind={assignM.isPending && assignM.variables?.label === p.label}
                busyUnbind={unbindM.isPending && unbindM.variables?.label === p.label}
              />
            ))}
            {proxiesQ.error && !refused && (
              <tr><td colSpan={7} className="p-4 text-err">{(proxiesQ.error as Error).message}</td></tr>
            )}
            {proxiesQ.isLoading && <SkeletonRows cols={7} rows={4} />}
            {(proxiesQ.data || refused) && !proxiesQ.isLoading && proxies.length === 0 && (
              <tr>
                <td colSpan={7} className="p-4">
                  <EmptyState size="sm" textClassName={EMPTY_TEXT} />
                </td>
              </tr>
            )}
          </tbody>
        </table>
        {proxies.length > 0 && (
          <Pager
            page={cur}
            pageCount={pageCount}
            onPage={setPage}
            pageSize={pageSize}
            onPageSize={proxies.length > SIZE_CHANGER_PAST ? setPageSize : undefined}
          />
        )}
      </div>

      <CreatorEgressTable
        proxies={proxies}
        accounts={proxiesQ.data?.accounts ?? []}
        loading={proxiesQ.isLoading}
        unavailable={!!proxiesQ.error}
        onTest={(label) => testM.mutate(label)}
        testResultFor={(label) => (testM.variables === label ? testM.data : undefined)}
        testingLabel={testM.isPending ? testM.variables ?? null : null}
      />

      {addOpen && (
        <AddProxyModal
          takenLabels={proxiesQ.data ? proxies.map((p) => p.label) : null}
          onSave={submitDraft}
          saving={createM.isPending}
          onClose={() => setAddOpen(false)}
        />
      )}

      {deleting !== null && (
        <DeleteProxyModal
          removing={removeM.isPending}
          onDelete={() => removeM.mutate(deleting)}
          onClose={() => setDeleting(null)}
        />
      )}

      {toast && (
        <div className="fixed top-2 inset-x-0 z-[2010] flex justify-center pointer-events-none">
          <div
            role={toast.ok ? "status" : "alert"}
            className="pointer-events-auto flex items-center gap-2 px-3 py-[9px] rounded-lg bg-bg-elev-1 shadow-lg text-sm"
          >
            <span
              aria-hidden
              className={`w-4 h-4 rounded-full ${toast.ok ? "bg-ok" : "bg-err"} text-white text-[11px] leading-4 text-center font-semibold`}
            >
              {toast.ok ? "✓" : "×"}
            </span>
            {toast.text}
          </div>
        </div>
      )}
    </div>
  );
}

function DeleteProxyModal({ removing, onDelete, onClose }: { removing: boolean; onDelete: () => void; onClose: () => void }) {
  return (
    <IfModal
      title="Delete proxy"
      onClose={onClose}
      closable={false}
      keyboard
      footer={
        <>
          <IfButton onClick={onClose}>Cancel</IfButton>
          <IfButton variant="primary" className="bg-err hover:bg-err/90" disabled={removing} onClick={onDelete}>
            {removing && <Loader2 size={14} className="animate-spin" aria-hidden />}
            Delete
          </IfButton>
        </>
      }
    >
      Are you sure you want to delete this proxy?
    </IfModal>
  );
}

export function pagerItems(page: number, pageCount: number): Array<number | "prev5" | "next5"> {
  const buf = 2;
  if (pageCount <= 3 + buf * 2) return Array.from({ length: pageCount }, (_, i) => i + 1);
  let left = Math.max(1, page - buf);
  let right = Math.min(page + buf, pageCount);
  if (page - 1 <= buf) right = 1 + buf * 2;
  if (pageCount - page <= buf) left = pageCount - buf * 2;
  const items: Array<number | "prev5" | "next5"> = [];
  for (let n = left; n <= right; n++) items.push(n);
  if (page - 1 >= buf * 2 && page !== 1 + 2) items.unshift("prev5");
  if (pageCount - page >= buf * 2 && page !== pageCount - 2) items.push("next5");
  if (left !== 1) items.unshift(1);
  if (right !== pageCount) items.push(pageCount);
  return items;
}

function Pager({ page, pageCount, onPage, pageSize, onPageSize }: {
  page: number; pageCount: number; onPage: (n: number) => void;
  pageSize: number; onPageSize?: (n: number) => void;
}) {
  const box = "min-w-8 h-8 px-1.5 rounded-md text-sm disabled:opacity-50 disabled:cursor-not-allowed";
  return (
    <nav aria-label="Pagination" className="flex items-center gap-2 mt-4 mb-10">
      <button type="button" aria-label="Previous page" className={box} disabled={page <= 1} onClick={() => onPage(page - 1)}>
        ‹
      </button>
      {pagerItems(page, pageCount).map((n) =>
        typeof n === "number" ? (
          <button
            key={n}
            type="button"
            aria-current={n === page ? "page" : undefined}
            className={`${box} ${n === page ? "border border-accent bg-transparent text-accent" : "hover:bg-white/[.08]"}`}
            onClick={() => onPage(n)}
          >
            {n}
          </button>
        ) : (
          <button
            key={n}
            type="button"
            aria-label={n === "prev5" ? "Previous 5 Pages" : "Next 5 Pages"}
            title={n === "prev5" ? "Previous 5 Pages" : "Next 5 Pages"}
            className={`${box} text-fg-dim hover:text-accent tracking-[2px]`}
            onClick={() => onPage(n === "prev5" ? Math.max(1, page - 5) : Math.min(pageCount, page + 5))}
          >
            •••
          </button>
        ),
      )}
      <button type="button" aria-label="Next page" className={box} disabled={page >= pageCount} onClick={() => onPage(page + 1)}>
        ›
      </button>
      {onPageSize && (
        <select
          aria-label="Page size"
          value={pageSize}
          onChange={(e) => onPageSize(Number(e.target.value))}
          className="h-8 ml-2 px-[11px] rounded-md bg-bg border border-border text-sm"
        >
          {PAGE_SIZES.map((n) => (
            <option key={n} value={n}>{n} / page</option>
          ))}
        </select>
      )}
    </nav>
  );
}

export function proxyStatus(proxy: ProxyMeta, test?: TestResult): { on: boolean; detail: string } {
  if (test) return test.ok ? { on: true, detail: test.ip ?? "" } : { on: false, detail: test.error || "failed" };
  const h = proxy.health;
  const r = h?.refusals;
  const span = r ? (r.window_s < 60 ? `${Math.round(r.window_s)} s` : `${Math.round(r.window_s / 60)} min`) : "";
  const rate = r ? `refusing ${Math.round(r.pct)}% (${span})` : "";
  const refusing = r && r.pct > 0 ? ` · ${rate}` : "";
  if (h && (h.state === "bad" || h.state === "rechecking")) {
    const since = h.bad_since ? ` since ${new Date(h.bad_since * 1000).toLocaleTimeString()}` : "";
    const next = h.state === "rechecking" ? "rechecking now" : h.next_recheck_at
      ? `recheck at ${new Date(h.next_recheck_at * 1000).toLocaleTimeString()}` : "rechecking";
    if (h.bad_reason === "flapping") {
      return { on: false, detail: r && r.pct > 0 ? `${rate}${since} — ${next}` : `was refusing — ${next}` };
    }
    return { on: false, detail: `unreachable${since} (${h.errors} refused) — ${next}${refusing}` };
  }
  return proxy.verified_ip ? { on: true, detail: proxy.verified_ip + refusing }
    : { on: false, detail: "unverified — run Test" + refusing };
}

function TypeCell({ scheme }: { scheme: string }) {
  if (scheme === "socks5") return <>socks</>;
  if (scheme === "https") return <span title={EXTRA_LABEL}>https</span>;
  return <>{scheme}</>;
}

const LINK_BTN = "h-8 px-[15px] text-sm whitespace-nowrap disabled:opacity-50 disabled:cursor-not-allowed";

function ProxyRow({
  proxy, accounts, onBind, onUnbind, onTest, onRemove,
  testResult, testing, removing, busyBind, busyUnbind,
}: {
  proxy: ProxiesResp["proxies"][number];
  accounts: AccountMeta[];
  onBind: (account_id: string) => void;
  onUnbind: (account_id: string) => void;
  onTest: () => void;
  onRemove: () => void;
  testResult?: TestResult;
  testing: boolean;
  removing: boolean;
  busyBind: boolean;
  busyUnbind: boolean;
}) {
  // Fall back to the legacy singular so a stale relay build doesn't blank the cell.
  const bound = (proxy.assigned_accounts && proxy.assigned_accounts.length > 0)
    ? proxy.assigned_accounts
    : proxy.assigned_account ? [proxy.assigned_account] : [];
  const boundIds = new Set(bound.map((b) => b.id));
  const unbound = accounts.filter((a) => !boundIds.has(a.id));
  const shared = bound.length > 1;
  const status = proxyStatus(proxy, testResult);
  return (
    <tr className={PROXY_TABLE.row}>
      <td className="p-4">{proxy.label}</td>
      <td className="p-4">{proxy.host}</td>
      <td className="p-4">{proxy.port}</td>
      <td className="p-4"><TypeCell scheme={proxy.scheme} /></td>
      <td className="p-4">
        <div className="flex flex-wrap items-center gap-1.5">
          {bound.map((b) => {
            const meta = accounts.find((a) => a.id === b.id);
            const color = meta?.color || (b as { color?: string | null }).color || "#666";
            return (
              <span
                key={b.id}
                className="inline-flex items-center gap-1.5 pl-1.5 pr-1 py-0.5 rounded-full text-[11px] border border-border bg-bg-elev-1"
              >
                <span className="w-2 h-2 rounded-full" style={{ background: color }} />
                <span className="truncate max-w-[140px] text-accent">{b.nickname || b.id}</span>
                <button
                  type="button"
                  onClick={() => onUnbind(b.id)}
                  disabled={busyUnbind}
                  title={`${EXTRA_LABEL}\nUnbind from this proxy`}
                  className="text-fg-dim hover:text-err leading-none px-1 disabled:opacity-50"
                  aria-label={`Unbind ${b.nickname || b.id}`}
                >
                  ×
                </button>
              </span>
            );
          })}
          {shared && (
            <span
              title={`${EXTRA_LABEL}\nMore than one OF account shares this proxy. OF can correlate accounts that egress from the same IP — only do this for accounts you intend to link.`}
              className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[11px] font-medium border bg-warn/15 text-warn border-warn/30 cursor-help"
            >
              <span aria-hidden>⚠</span>
              <span>shared egress</span>
            </span>
          )}
          {unbound.length > 0 && (
            <select
              value=""
              onChange={(e) => {
                if (e.target.value) onBind(e.target.value);
              }}
              disabled={busyBind}
              title={`${EXTRA_LABEL}\nBind a Creator to this proxy`}
              className="bg-bg border border-border rounded-md px-2 py-1 text-[11px] disabled:opacity-50"
            >
              <option value="">{bound.length === 0 ? "+ assign account" : "+ add model"}</option>
              {unbound.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.nickname || a.id}
                </option>
              ))}
            </select>
          )}
        </div>
      </td>
      <td className="p-4">
        <div className="flex flex-col">
          <span className={status.on ? "text-accent" : "text-err"}>{status.on ? STATUS_ON : STATUS_OFF}</span>
          {status.detail && (
            <span className="font-mono text-xs text-fg-dim" title={EXTRA_LABEL}>{status.detail}</span>
          )}
        </div>
      </td>
      <td className="p-4">
        <div className="flex items-center whitespace-nowrap">
          <button type="button" className={`${LINK_BTN} text-accent`} disabled title="not wired">
            Edit
          </button>
          {bound.length === 0 && (
            <button type="button" className={`${LINK_BTN} text-err`} disabled={removing} onClick={onRemove}>
              {removing ? "Deleting…" : "Delete"}
            </button>
          )}
          <button
            type="button"
            className={`${LINK_BTN} text-accent`}
            disabled={testing}
            onClick={onTest}
            title={EXTRA_LABEL}
          >
            {testing ? "Testing…" : "Test"}
          </button>
        </div>
      </td>
    </tr>
  );
}
