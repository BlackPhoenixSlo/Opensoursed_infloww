"use client";

/**
 * ProxiesTable — Creators > Custom proxy, laid out from its Layout capture
 * (`docs/infloww-layouts/creators-proxy.md`, ticket 17): the header, then the proxy
 * table with the capture's seven columns, "No data" and 10 rows a page. Every cell comes
 * from the one proxies read. Bind, Unbind, Test and the shared-egress warning are ours,
 * titled `EXTRA_LABEL`; Remove is the capture's Delete. "+ Add new proxy" opens the
 * capture's add modal (`AddProxyModal`, ticket 18), which holds the manual form and the paste box. Under the table,
 * `CreatorEgressTable` (ours, ticket 19) shows each Creator's egress from the same proxies read. Ticket 62: an add is
 * checked through Test and kept only if the check passes, a failed add is antd's message toast, Delete asks in the
 * capture's modal, the loading state is antd's spinner and the pager folds and changes size as antd's does.
 *
 * Powered by:
 *   GET    /admin/proxies                 list + assignments enriched with account meta
 *   POST   /admin/proxies                 upsert {label, host, port, scheme, username?, password?, notes?}
 *   POST   /admin/proxies/bulk            paste many, one per line {text, scheme} (docs/proxies.md)
 *   DELETE /admin/proxies/{label}         remove; 409 while a Creator is bound (Infloww's "Proxy already in use")
 *   POST   /admin/proxies/assign          bind a proxy to an account_id (or null to unassign)
 *   POST   /admin/proxies/{label}/test    egress-IP check
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";

import { relay, type ProxyMeta, type AccountMeta } from "@/lib/relay";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import { Button } from "@/components/ui/primitives";
import { EmptyState, InflowwPageHeader } from "@/components/ui/infloww";
import AddProxyModal, {
  EMPTY_DRAFT, draftLabel, useEscape, type BulkResp, type ProxyDraft, type ProxyScheme,
} from "@/components/setup/AddProxyModal";
import CreatorEgressTable, {
  EMPTY_TEXT, PROXY_TABLE, proxyTh, type TestResult,
} from "@/components/setup/CreatorEgressTable";
import { SkeletonRows } from "@/components/ui/Skeleton";

interface ProxiesResp {
  proxies: Array<
    ProxyMeta & {
      // Backend now returns a list (many accounts may share a proxy);
      // `assigned_account` (singular) is kept around as legacy mirror.
      assigned_accounts?: Array<{ id: string; nickname?: string | null; color?: string | null }>;
      assigned_account?: { id: string; nickname?: string | null } | null;
    }
  >;
  accounts: AccountMeta[];
}

/** creators-proxy#23: 10 a page at first; antd's size changer offers these past 50 rows
 *  (`totalBoundaryShowSizeChanger:50`, `pageSizeOptions:["10","20","50","100"]`, vendor.bab480ce.js). */
const PAGE_SIZES = [10, 20, 50, 100] as const;
const SIZE_CHANGER_PAST = 50;

/** creators-proxy#14's two states, `creators0045` (the status on) and `creators0289` (off). The bundle ships no
 *  English for either key, so these words stand in until its en locale chunk is read (the capture's Notes). */
const STATUS_ON = "Available";
const STATUS_OFF = "Unavailable";

/** A chatter (or a signed-out caller) is refused the proxies read: the page draws its controls not wired instead of
 *  an error nobody can act on. 401 as well as 403, as `ManagedAgencyKeysCard` reads a refusal; read off the error's
 *  `status` (a `RelayError`'s) rather than `instanceof`, so a test's relay mock need not carry the class. */
const isRefused = (err: unknown) => {
  const status = (err as { status?: unknown } | null)?.status;
  return status === 401 || status === 403;
};

export default function ProxiesTable() {
  const qc = useQueryClient();
  const [addOpen, setAddOpen] = useState(false);
  const [draft, setDraft] = useState<ProxyDraft>(EMPTY_DRAFT);
  /** #27, #37: antd's `message.error` / `message.success`, at the top and over the modal, gone after its 3s. */
  const [toast, setToast] = useState<{ ok: boolean; text: string } | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [bulkText, setBulkText] = useState("");
  const [bulkScheme, setBulkScheme] = useState<ProxyScheme>("http");

  const proxiesQ = useQuery<ProxiesResp>({
    queryKey: ["proxies"],
    queryFn: () => relay.get<ProxiesResp>("/admin/proxies"),
    staleTime: 60_000,
    // A refusal will not change on a retry.
    retry: (n, err) => !isRefused(err) && n < 3,
  });
  const refused = isRefused(proxiesQ.error);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState<number>(PAGE_SIZES[0]);

  // Single mutation key, used for both bind and unbind (same per-row spinner
  // semantics — `variables.label` lets a row know which action is in flight).
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

  // #37: the bundle checks a proxy before it adds one. The Relay probes only a registered label (`POST
  // /admin/proxies/{label}/test`) and this Phase adds no route, so the add registers, runs that check, and removes
  // the proxy again when the check fails: a failing proxy ends unregistered, as in the bundle.
  const createM = useMutation({
    mutationFn: async (body: { label: string } & Record<string, unknown>) => {
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
      setDraft(EMPTY_DRAFT);
      setAddOpen(false);
      // `creators0317` has no English on disk; "Proxy added" stands in.
      setToast({ ok: true, text: "Proxy added" });
    },
    onError: (err: Error) => {
      qc.invalidateQueries({ queryKey: ["proxies"] });
      setToast({ ok: false, text: err.message });
    },
  });

  // The pasted text carries proxy passwords, so it is read from state in the
  // closure and never becomes a mutation variable (mutations can be persisted).
  const bulkM = useMutation({
    mutationFn: () => relay.post<BulkResp>("/admin/proxies/bulk", { text: bulkText, scheme: bulkScheme }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["proxies"] });
      if (r.errors.length === 0) setBulkText("");
    },
  });

  const removeM = useMutation({
    mutationFn: (label: string) => relay.delete<unknown>(`/admin/proxies/${encodeURIComponent(label)}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["proxies"] });
      qc.invalidateQueries({ queryKey: ["accounts"] });
      setDeleting(null);
    },
    // A 409 "Proxy already in use by …" means the list was stale (the row hides Delete while a Creator is bound):
    // refetch it so the row shows its Creators.
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

  // The relay's POST upserts: an existing label is overwritten in place. The modal keeps Add proxy off for a label
  // the registry already holds (`draftProblem`), so a typo cannot silently clobber a working proxy.
  function submitDraft() {
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
  // A delete or a larger page can empty the last page; show the one before it.
  const cur = Math.min(page, pageCount);
  const shown = proxies.slice((cur - 1) * pageSize, cur * pageSize);

  return (
    // Full width, as Infloww's header rule runs edge to edge (page-parity 03).
    <div>
      {/* creators-proxy#4, #6: a 48px header, 0 24px, a 1px rule under it; the title 16px, weight 600. #7, #8: the
          primary, 32px, 0 15px, 4px corners, 14px weight 400, one line. */}
      <InflowwPageHeader
        title="Manage your custom proxies"
        actions={
        <Button
          className="h-8 py-0 px-[15px] rounded text-sm font-normal whitespace-nowrap"
          disabled={refused}
          title={refused ? "not wired" : undefined}
          onClick={() => {
            setDraft(EMPTY_DRAFT);
            setToast(null);
            bulkM.reset();
            setAddOpen(true);
          }}
        >
          + Add new proxy
        </Button>
        }
      />

      {/* #9: the table 24px 40px in (16px at the sides on a phone). */}
      <div className="my-6 mx-4 md:mx-10 overflow-auto">
        {/* #10, #17 to #19: one auto-layout table, 14px, 16px cells, the head weight 600 and start-aligned. */}
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
            {/* #20, #21: antd's simple empty (ticket 00's `EmptyState size="sm"`: the tray, then "No data"), 32px
                above and below, once the read has answered. #22: antd's Table draws that empty body faded under a
                spinner while the read runs; ours draws placeholder rows instead (the owner's every-page-paints-its-
                layout ask, 2026-10-29), so "No data" never shows before the answer. */}
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

      {/* Ours (ticket 19): which IP each Creator talks from, over the same proxies answer; no read of its own. */}
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
          draft={draft}
          onDraft={setDraft}
          takenLabels={proxiesQ.data ? proxies.map((p) => p.label) : null}
          onSave={submitDraft}
          saving={createM.isPending}
          bulkText={bulkText}
          onBulkText={setBulkText}
          bulkScheme={bulkScheme}
          onBulkScheme={setBulkScheme}
          onBulk={() => bulkM.mutate()}
          bulkPending={bulkM.isPending}
          bulkError={bulkM.error?.message ?? null}
          bulkResult={bulkM.data}
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

      {/* #27, #37: antd's message, 8px from the top, centred, over the modal's layer. */}
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

/** creators-proxy#38: `DeleteProxy`, an `XModal` (antd's 520px, centred, no close cross) titled with the question,
 *  then Cancel and the danger primary Delete. The box is #25's: 10px corners, a 22px 24px header, 16px body, 11px 24px
 *  footer. A mask click closes it, as `DeleteProxy` leaves antd's `maskClosable` on; so does Escape. */
function DeleteProxyModal({ removing, onDelete, onClose }: { removing: boolean; onDelete: () => void; onClose: () => void }) {
  useEscape(onClose);
  const foot = "h-8 py-0 px-[15px] min-w-[72px] rounded text-sm font-normal whitespace-nowrap";
  return (
    <div className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/70" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="delete-proxy-title"
        className="w-[520px] max-w-[calc(100vw-32px)] rounded-[10px] overflow-hidden bg-[#1f1f1f] shadow-xl text-sm [html[data-theme=light]_&]:bg-white"
        onClick={(e) => e.stopPropagation()}
      >
        <div id="delete-proxy-title" className="px-6 py-[22px] text-base font-semibold">Delete proxy</div>
        <div className="p-4">Are you sure you want to delete this proxy?</div>
        <div className="flex items-center justify-end gap-2 px-6 py-[11px]">
          <Button variant="ghost" className={foot} onClick={onClose}>
            Cancel
          </Button>
          <Button className={`${foot} bg-err hover:bg-err/90 text-white`} disabled={removing} onClick={onDelete}>
            {removing && <Loader2 size={14} className="animate-spin" aria-hidden />}
            Delete
          </Button>
        </div>
      </div>
    </div>
  );
}

/** rc-pagination's run, as antd 5 draws it (vendor.bab480ce.js): every page up to 7, else 2 each side of the current
 *  page, the first and last pages, and a "•••" jump of 5 where a run is folded. */
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

/** creators-proxy#23: under the table at the left (the app moves antd's bottom right there), 40px under it; the size
 *  changer follows the pages when the caller passes `onPageSize` (past 50 rows). */
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

/** The capture's state (#14) from the latest test, else the relay's health (a proxy it holds bad is Unavailable,
 *  whatever the stored verification says), else the stored verification; the detail under it is ours. */
export function proxyStatus(proxy: ProxyMeta, test?: TestResult): { on: boolean; detail: string } {
  if (test) return test.ok ? { on: true, detail: test.ip ?? "" } : { on: false, detail: test.error || "failed" };
  const h = proxy.health;
  if (h && (h.state === "bad" || h.state === "rechecking")) {
    const since = h.bad_since ? ` since ${new Date(h.bad_since * 1000).toLocaleTimeString()}` : "";
    const next = h.state === "rechecking" ? "rechecking now" : h.next_recheck_at
      ? `recheck at ${new Date(h.next_recheck_at * 1000).toLocaleTimeString()}` : "rechecking";
    return { on: false, detail: `unreachable${since} (${h.errors} refused) — ${next}` };
  }
  return proxy.verified_ip ? { on: true, detail: proxy.verified_ip } : { on: false, detail: "unverified — run Test" };
}

/** #12: the bundle's type words, http and socks (the relay's socks5); the relay's https is ours. */
function TypeCell({ scheme }: { scheme: string }) {
  if (scheme === "socks5") return <>socks</>;
  if (scheme === "https") return <span title={EXTRA_LABEL}>https</span>;
  return <>{scheme}</>;
}

/** #16's link buttons: 32px, 0 15px, 14px, one line. */
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
  // Server returns `assigned_accounts: [...]`; fall back to the legacy
  // singular so a stale relay (running on an old build) doesn't blank the
  // cell. Sort by nickname for stable rendering across refetches.
  const bound = (proxy.assigned_accounts && proxy.assigned_accounts.length > 0)
    ? proxy.assigned_accounts
    : proxy.assigned_account ? [proxy.assigned_account] : [];
  const boundIds = new Set(bound.map((b) => b.id));
  const unbound = accounts.filter((a) => !boundIds.has(a.id));
  const shared = bound.length > 1;
  const status = proxyStatus(proxy, testResult);
  return (
    <tr className={PROXY_TABLE.row}>
      {/* #11, #12: label, host, port and type, plain text. */}
      <td className="p-4">{proxy.label}</td>
      <td className="p-4">{proxy.host}</td>
      <td className="p-4">{proxy.port}</td>
      <td className="p-4"><TypeCell scheme={proxy.scheme} /></td>
      {/* #13: the Creator. The bundle names one; ours lists every bound Creator as a chip. */}
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
      {/* #14: the capture's two states, then ours under it: the verified IP, or why there is none. */}
      <td className="p-4">
        <div className="flex flex-col">
          <span className={status.on ? "text-accent" : "text-err"}>{status.on ? STATUS_ON : STATUS_OFF}</span>
          {status.detail && (
            <span className="font-mono text-xs text-fg-dim" title={EXTRA_LABEL}>{status.detail}</span>
          )}
        </div>
      </td>
      {/* #16: Edit, then Delete only while no Creator is bound; Test after them is ours. */}
      <td className="p-4">
        <div className="flex items-center whitespace-nowrap">
          {/* The relay keys a proxy by its label and has no route that renames one. */}
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

