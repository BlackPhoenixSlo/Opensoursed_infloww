"use client";


import { EmptyState } from "@/components/ui/infloww";
import { ExtraTag } from "@/components/ui/primitives";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import type { AccountMeta, ProxyMeta } from "@/lib/relay";
import { cn } from "@/lib/utils";
import { SkeletonRows } from "@/components/ui/Skeleton";

export const PROXY_TABLE = {
  headRow: "bg-white/4 [html[data-theme=light]_&]:bg-[#fafafa]",
  th: "p-4 text-start font-semibold first:rounded-tl-lg last:rounded-tr-lg",
  thDivider: "relative after:absolute after:right-0 after:top-1/2 after:h-[22px] after:w-px after:-translate-y-1/2 after:bg-white/6 [html[data-theme=light]_&]:after:bg-[#f0f0f0]",
  row: "border-b border-white/6 last:border-0 [html[data-theme=light]_&]:border-[#f0f0f0]",
} as const;
export const proxyTh = (last = false) => cn(PROXY_TABLE.th, !last && PROXY_TABLE.thDivider);
export const EMPTY_TEXT = "text-[#595959] [html[data-theme=light]_&]:text-black/25";

export type TestResult = { ok: boolean; ip?: string | null; geo?: string | null; error?: string | null };

function boundProxy(proxies: ProxyMeta[], accountId: string): ProxyMeta | undefined {
  return proxies.find((p) =>
    (p.assigned_accounts && p.assigned_accounts.length > 0
      ? p.assigned_accounts.some((a) => a.id === accountId)
      : p.assigned_account?.id === accountId),
  );
}

function egressOf(proxy: ProxyMeta, test?: TestResult): { ip: string | null; note: string } {
  if (test) return test.ok ? { ip: test.ip ?? null, note: "" } : { ip: null, note: test.error || "test failed" };
  return proxy.verified_ip ? { ip: proxy.verified_ip, note: "" } : { ip: null, note: "unverified — run Test" };
}

export default function CreatorEgressTable({
  proxies, accounts, loading, unavailable, onTest, testResultFor, testingLabel,
}: {
  proxies: ProxyMeta[];
  accounts: AccountMeta[];
  loading: boolean;
  unavailable: boolean;
  onTest: (label: string) => void;
  testResultFor: (label: string) => TestResult | undefined;
  testingLabel: string | null;
}) {
  return (
    <section className="mx-4 md:mx-10 mb-10" title={EXTRA_LABEL}>
      <div className="flex items-center gap-2 mb-4">
        <h2 id="creator-egress-heading" className="text-base font-semibold">Creator egress</h2>
        <ExtraTag />
      </div>
      <div className="overflow-auto">
        <table className="w-full text-sm" aria-labelledby="creator-egress-heading">
          <thead>
            <tr className={PROXY_TABLE.headRow}>
              <th className={proxyTh()}>Creator</th>
              <th className={proxyTh()}>Creator ID</th>
              <th className={proxyTh()}>Egress</th>
              <th className={proxyTh()}>Session</th>
              <th className={proxyTh(true)}>Action</th>
            </tr>
          </thead>
          <tbody>
            {accounts.map((a) => {
              const p = boundProxy(proxies, a.id);
              const egress = p ? egressOf(p, testResultFor(p.label)) : null;
              const testing = !!p && testingLabel === p.label;
              return (
                <tr key={a.id} className={PROXY_TABLE.row}>
                  <td className="p-4">{a.nickname || a.id}</td>
                  <td className="p-4 font-mono text-xs">{a.id}</td>
                  <td className="p-4">
                    {p && egress ? (
                      <div className="flex flex-col">
                        {egress.ip && <span className="font-mono">{egress.ip}</span>}
                        <span className="text-xs text-fg-dim">
                          <span>{p.label}</span>
                          {egress.note && <> · {egress.note}</>}
                        </span>
                      </div>
                    ) : (
                      <span
                        className="text-fg-dim"
                        title="not wired: the bundle gives each Creator an automatic proxy; the Relay has none, so this Creator talks from the Relay's own IP"
                      >
                        No custom proxy
                      </span>
                    )}
                  </td>
                  <td className="p-4">
                    {a.has_session ? "Has session" : <span className="text-err">No session</span>}
                  </td>
                  <td className="p-4">
                    <button
                      type="button"
                      className="h-8 px-[15px] text-sm text-accent whitespace-nowrap disabled:opacity-50 disabled:cursor-not-allowed"
                      disabled={!p || testing}
                      title={p ? `Test proxy ${p.label}` : "No custom proxy to test: this Creator leaves from the relay's own IP"}
                      onClick={() => p && onTest(p.label)}
                    >
                      {testing ? "Testing…" : "Test"}
                    </button>
                  </td>
                </tr>
              );
            })}
            {loading && (
              <SkeletonRows cols={5} rows={4} />
            )}
            {!loading && (unavailable || accounts.length === 0) && (
              <tr><td colSpan={5} className="p-4"><EmptyState size="sm" textClassName={EMPTY_TEXT} /></td></tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
