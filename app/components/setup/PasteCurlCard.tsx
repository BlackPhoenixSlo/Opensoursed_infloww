"use client";

/**
 * PasteCurlCard — the primary bootstrap path.
 *
 * User installs the Chatterly Login (or No-Teleport Login) browser extension,
 * signs in to OF, clicks "Copy curl," and pastes the result here. We POST it
 * to /admin/session/bootstrap with `mode: 'paste-curl'`. The relay parses
 * cookies + signed headers + the `x-relay-static-param` extension header to
 * derive signing rules for the current OF revision.
 *
 * Optional fields:
 *   • Proxy to attach — drop-down of registered proxies; we surface a
 *     teleport-warning confirm since cookies are minted on the user's home
 *     IP and outbound traffic now routes through the proxy. (Plan §13.3.)
 *     "Paste a new proxy…" takes one line in any format; it is registered via
 *     POST /admin/proxies/bulk first and its label goes through the same
 *     assign step. The line (it can carry a password) is never a mutation
 *     variable, query key or URL.
 *   • Advanced override — manual static_param for a brand-new OF rev we
 *     haven't seen, fallback if the extension didn't capture it. Hidden
 *     by default under a <details>.
 *
 * Result panel shows the parsed response so you can see the new account_id
 * + which session file was written.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Download } from "lucide-react";

import { relay, type BootstrapResponse, type ProxyMeta, RelayError } from "@/lib/relay";
import { Badge, Button, Card, Input, Textarea } from "@/components/ui/primitives";
import { EXTENSION_ID } from "@/components/setup/useExtensionProbe";
import { useInDesktopApp } from "@/hooks/useInDesktopApp";
import { BRAND_NAME } from "@/lib/brand";

const EXTENSION_URL = `https://chromewebstore.google.com/detail/chatterly-login-capture/${EXTENSION_ID}`;

/** Select value for "Paste a new proxy…"; never a real label. */
const PASTE_PROXY = "__paste__";

interface ProxiesResp {
  proxies: ProxyMeta[];
}

interface BootstrapBody {
  mode: "paste-curl";
  curl: string;
  nickname?: string;
  make_active?: boolean;
  static_param_override?: string;
}

/** `extInstalled` is the page-mount probe's answer (useExtensionProbe): null while checking. The card never probes.
 *  Inside the Add creator flow, `onLinked` hears the new account (when the proxy attach failed, only after Retry
 *  succeeds or Continue is pressed), and the flow's Nickname and Proxy selection come in as `initialNickname` and
 *  `initialProxyLabel`. `attach` (the flow picked Inflowwww proxy) replaces the "Attach proxy" select: it runs as the
 *  card's attach step, after the session is captured and before `onLinked`. */
export default function PasteCurlCard({ extInstalled, onLinked, initialNickname = "", initialProxyLabel = "", attach }: {
  extInstalled: boolean | null;
  onLinked?: (accountId: string) => void;
  initialNickname?: string;
  initialProxyLabel?: string;
  attach?: (accountId: string) => Promise<void>;
}) {
  const qc = useQueryClient();
  const inApp = useInDesktopApp();
  const [curl, setCurl] = useState("");
  const [nickname, setNickname] = useState(initialNickname);
  const [makeActive, setMakeActive] = useState(true);
  const [proxyLabel, setProxyLabel] = useState(initialProxyLabel);
  const [pastedProxy, setPastedProxy] = useState("");
  const [staticOverride, setStaticOverride] = useState("");
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  // An account captured but whose attach failed: Retry re-runs the attach step, Continue goes on without it.
  // `onLinked` waits for either, so the error stays readable.
  const [pending, setPending] = useState<{ accountId: string; label: string } | null>(null);

  const proxiesQ = useQuery<ProxiesResp>({
    queryKey: ["proxies", "list"],
    queryFn: () => relay.get<ProxiesResp>("/admin/proxies"),
    staleTime: 60_000,
  });

  const bootstrapM = useMutation<BootstrapResponse, RelayError, BootstrapBody>({
    mutationFn: (body) => relay.post<BootstrapResponse>("/admin/session/bootstrap", body),
  });

  const attachProxyM = useMutation({
    mutationFn: ({ label, account_id }: { label: string; account_id: string }) =>
      relay.post<unknown>("/admin/proxies/assign", { label, account_id }),
  });

  const reloadM = useMutation({
    mutationFn: (account_id: string) =>
      relay.post<unknown>(`/admin/reload-session?account_id=${encodeURIComponent(account_id)}`),
  });

  async function submit() {
    setResult(null);
    setPending(null);
    if (!curl.trim().startsWith("curl")) {
      setResult({ ok: false, text: "Must start with `curl ...`" });
      return;
    }
    const pasting = proxyLabel === PASTE_PROXY;
    if (pasting && !pastedProxy.trim()) {
      setResult({ ok: false, text: "Paste a proxy line or pick another option." });
      return;
    }
    if (attach || proxyLabel) {
      const confirmed = window.confirm(
        `Attach ${attach ? "the chosen proxy" : pasting ? "proxy (the pasted one)" : `proxy "${proxyLabel}"`} to this account?\n\n` +
        `OnlyFans will see every signed call egress from the proxy IP. The ` +
        `cookies you're pasting were minted from your own browsing IP, so ` +
        `OF effectively sees the account "teleport" to the proxy. Only safe ` +
        `when the proxy IP is geographically/ASN-close to where you logged in.\n\n` +
        `OK to attach. Cancel to go back; nothing is sent.`,
      );
      if (!confirmed) return;
    }

    let label = proxyLabel;
    if (pasting) {
      try {
        const r = await relay.post<{ added: Array<{ label: string }>; errors: Array<{ reason: string }> }>(
          "/admin/proxies/bulk",
          { text: pastedProxy.trim(), scheme: "http" },
        );
        if (!r.added[0]) {
          setResult({ ok: false, text: `Proxy not added: ${r.errors[0]?.reason ?? "unrecognised format"}` });
          return;
        }
        label = r.added[0].label;
      } catch (err) {
        setResult({ ok: false, text: `Proxy not added: ${(err as Error).message}` });
        return;
      }
    }

    const body: BootstrapBody = {
      mode: "paste-curl",
      curl,
      make_active: makeActive,
    };
    if (nickname.trim()) body.nickname = nickname.trim();
    if (staticOverride.trim()) body.static_param_override = staticOverride.trim();

    try {
      const data = await bootstrapM.mutateAsync(body);
      if (data.account_id && !(await attachStep(data.account_id, label))) return;
      setCurl("");
      await finish(
        data.account_id || null,
        `✓ Bootstrapped account ${data.account_id} (user_id ${data.user_id})\n` +
        `Session file: ${data.session_file}\n` +
        `x-of-rev: ${data.x_of_rev}`,
      );
    } catch (err) {
      const e = err as RelayError;
      setResult({
        ok: false,
        text:
          `${e.status} FAILED\n\n` +
          (typeof e.body === "string" ? e.body : JSON.stringify(e.body, null, 2)),
      });
    }
  }

  // Invalidate every cache that depends on accounts/proxies.
  function refreshCaches() {
    qc.invalidateQueries({ queryKey: ["accounts"] });
    qc.invalidateQueries({ queryKey: ["proxies"] });
    qc.invalidateQueries({ queryKey: ["drift"] });
    qc.invalidateQueries({ queryKey: ["health-all"] });
  }

  /** The attach step: bind the chosen proxy (`attach`, else the selected label), then reload the session. True when
   *  there is nothing to attach or it all worked; on failure the error stays in the card with Retry and Continue. */
  async function attachStep(accountId: string, label: string): Promise<boolean> {
    if (!attach && !label) return true;
    let bound = false;
    try {
      if (attach) await attach(accountId);
      else await attachProxyM.mutateAsync({ label, account_id: accountId });
      bound = true;
      await reloadM.mutateAsync(accountId);
      return true;
    } catch (err) {
      const msg = (err as Error).message;
      setResult({
        ok: true,
        text: bound
          ? `Session captured (account ${accountId}) and the proxy is attached, but reloading the session failed:\n` +
            `${msg}\n\nPress Retry to reload it.`
          : `Session captured (account ${accountId}), but proxy attach failed:\n${msg}\n\n` +
            (attach ? "Press Retry, or Continue without it." : "Press Retry, or attach it later under Creators → Custom proxy."),
      });
      // The account was created before the proxy step, so refresh even on the failure path.
      refreshCaches();
      setPending({ accountId, label });
      return false;
    }
  }

  /** After the attach step (or Continue past it): report, hand the account on. */
  async function finish(accountId: string | null, headline: string) {
    setPending(null);
    setResult({ ok: true, text: headline });
    refreshCaches();
    if (accountId) onLinked?.(accountId);
  }

  async function retry() {
    if (!pending) return;
    const { accountId, label } = pending;
    setPending(null);
    if (await attachStep(accountId, label)) {
      setCurl("");
      await finish(accountId, `✓ Proxy attached to account ${accountId}`);
    }
  }

  return (
    <Card className="space-y-4">
      <div>
        <h2 className="text-base font-semibold mb-1">Paste cURL</h2>
        <p className="text-sm text-fg-dim leading-relaxed mb-3">
          Install the <strong>Chatterly Login Capture</strong> extension, sign
          in to OnlyFans, click <strong>Copy cURL</strong>, and paste here.
          The extension injects <code>x-relay-static-param</code> so this
          works on any new OF revision.
        </p>
        {extInstalled === true ? (
          <div className="inline-flex items-center gap-2 px-4 py-2.5 rounded-lg bg-ok/10 border border-ok/30 text-ok font-medium text-sm">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z" />
            </svg>
            Extension installed — click the puzzle icon in your Chrome toolbar to open it
          </div>
        ) : (
          <a
            href={EXTENSION_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-lg bg-accent text-white hover:bg-accent-hover font-medium text-sm"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 3a7 7 0 016.32 4H12a3 3 0 00-2.83 2H5.68A7 7 0 0112 5zm-7 7c0-.69.1-1.36.28-2L8.5 17.5A7 7 0 015 12zm7 7a7 7 0 01-1.5-.16L13.83 13a3 3 0 002.83-2h2.96A7 7 0 0112 19zm0-4a3 3 0 110-6 3 3 0 010 6z" />
            </svg>
            {extInstalled === null ? "Open Chrome Extension" : "Install Chrome Extension"}
          </a>
        )}
        {/* The desktop app, in the same row (a plain <a>: /download is a static file outside the router). Left
            out inside the app, where desktop/preload.js finds the "Install Chrome Extension" link by its text and
            puts "Connect OnlyFans (app)" right after it. */}
        {!inApp && (
          <a
            href="/download"
            title={`Get the ${BRAND_NAME} desktop app for Mac and Windows`}
            className="ml-2 inline-flex items-center gap-2 px-4 py-[9px] rounded-lg border border-border text-fg hover:bg-bg-elev-1 font-medium text-sm"
          >
            <Download aria-hidden className="w-[18px] h-[18px]" />
            Download app
          </a>
        )}
      </div>

      <Textarea
        rows={6}
        placeholder="curl 'https://onlyfans.com/api2/v2/...' -H 'sign: …' -H 'time: …' -H 'user-id: …' -H 'x-bc: …' -H 'x-of-rev: …' -H 'x-relay-static-param: …' -b 'auth_id=…; sess=…; …'"
        value={curl}
        onChange={(e) => setCurl(e.target.value)}
      />

      {/* Optional fields */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div>
          <label className="block text-xs text-fg-dim mb-1">Nickname (optional)</label>
          <Input
            placeholder="e.g. Bella, Mia, Test-burner"
            value={nickname}
            onChange={(e) => setNickname(e.target.value)}
          />
        </div>
        {!attach && <div>
          <label className="block text-xs text-fg-dim mb-1">Attach proxy (optional)</label>
          <select
            value={proxyLabel}
            onChange={(e) => setProxyLabel(e.target.value)}
            className="w-full bg-bg border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-accent"
          >
            <option value="">— none (relay egresses on server WAN IP) —</option>
            {(proxiesQ.data?.proxies || []).map((p) => (
              <option key={p.label} value={p.label}>
                {p.label} · {p.host}:{p.port}
              </option>
            ))}
            <option value={PASTE_PROXY}>Paste a new proxy…</option>
          </select>
          {proxyLabel === PASTE_PROXY && (
            <Input
              aria-label="New proxy"
              className="mt-2 font-mono"
              placeholder="user:pass@host:port or host:port:user:pass"
              autoComplete="off"
              spellCheck={false}
              value={pastedProxy}
              onChange={(e) => setPastedProxy(e.target.value)}
            />
          )}
        </div>}
      </div>

      <label className="flex items-center gap-2 text-xs text-fg-dim">
        <input
          type="checkbox"
          checked={makeActive}
          onChange={(e) => setMakeActive(e.target.checked)}
          className="accent-accent"
        />
        Flip this account to the relay&apos;s default after bootstrap
      </label>

      {(attach || proxyLabel) && (
        <div className="text-[11px] text-warn bg-warn/10 border border-warn/30 rounded-lg p-3 leading-relaxed">
          ⚠ <strong>Teleport warning:</strong> the curl&apos;s cookies were minted
          from <em>your</em> browsing IP. Attaching this proxy makes every signed
          call afterwards egress from the proxy IP — OF sees the account hop
          continents. Only safe when the proxy IP is geographically close to
          your sign-in IP.
        </div>
      )}

      <details className="text-xs">
        <summary className="cursor-pointer text-fg-dim hover:text-fg">
          advanced: override <code>static_param</code> (only if you&apos;re on an
          OF revision we haven&apos;t seen and the extension didn&apos;t inject one)
        </summary>
        <Input
          placeholder="static_param (32 chars; usually leave blank)"
          value={staticOverride}
          onChange={(e) => setStaticOverride(e.target.value)}
          className="mt-2 font-mono"
        />
      </details>

      <Button
        type="button"
        onClick={submit}
        disabled={!curl.trim() || bootstrapM.isPending}
      >
        {bootstrapM.isPending ? "Bootstrapping…" : "Bootstrap from cURL"}
      </Button>

      {/* Result panel */}
      {result && (
        <pre
          className={
            "bg-bg-elev-1 border border-border rounded-lg p-3 text-[11px] font-mono whitespace-pre-wrap overflow-auto max-h-60 " +
            (result.ok ? "text-ok" : "text-err")
          }
        >
          {result.text}
        </pre>
      )}
      {pending && (
        <div className="flex gap-2">
          <Button type="button" onClick={() => void retry()}>Retry</Button>
          <Button
            type="button" variant="secondary"
            onClick={() => { setCurl(""); void finish(pending.accountId, `✓ Bootstrapped account ${pending.accountId} without a proxy`); }}
          >
            Continue
          </Button>
        </div>
      )}
    </Card>
  );
}
