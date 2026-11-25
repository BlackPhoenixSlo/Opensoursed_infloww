"use client";


import { useQueryClient } from "@tanstack/react-query";
import { useReducer } from "react";

import { relay, type BootstrapResponse, type RelayError } from "@/lib/relay";
import { accountSessionCaptured } from "@/lib/accountSession";
import { EditorFooter } from "@/components/ui/ifModal";
import { IfButton, IfHelp, IfInput, IfLabel, IfTextArea } from "@/components/ui/infloww";
import { EXTENSION_ID } from "@/components/setup/useExtensionProbe";
import { reloadSession } from "@/components/setup/proxyApi";
import { useReportBusy } from "@/components/setup/useReportBusy";
import {
  buildBootstrapBody, canSubmit, continueText, curlHint, extensionBusy, initialPasteCurl, pasteCurlReducer,
} from "@/components/setup/pasteCurl";
import { BRAND_NAME } from "@/lib/brand";

const EXTENSION_URL = `https://chromewebstore.google.com/detail/chatterly-login-capture/${EXTENSION_ID}`;

const PASTE_FORM_ID = "extension-login-form";

export default function PasteCurlCard({ extInstalled, onLinked, initialNickname = "", attach, active = true, onBusy }: {
  extInstalled: boolean | null;
  onLinked?: (accountId: string) => void;
  initialNickname?: string;
  attach?: (accountId: string) => Promise<boolean>;
  active?: boolean;
  onBusy?: (busy: boolean) => void;
}) {
  const qc = useQueryClient();
  const [state, dispatch] = useReducer(pasteCurlReducer, undefined, initialPasteCurl);
  const { curl, staticOverride, result, pending } = state;
  const hint = curlHint(curl);
  useReportBusy(extensionBusy(state), onBusy);

  async function submit() {
    dispatch({ type: "submitStart" });
    try {
      const data = await relay.post<BootstrapResponse>("/admin/session/bootstrap", buildBootstrapBody(state, initialNickname));
      // Capture already replaced the session, even if proxy attach later fails.
      if (data.account_id) accountSessionCaptured(data.account_id);
      if (data.account_id && !(await attachStep(data.account_id))) return;
      await finish(
        data.account_id || null,
        `Linked account ${data.account_id} (user_id ${data.user_id})\n` +
        `Session file: ${data.session_file}\n` +
        `x-of-rev: ${data.x_of_rev}`,
      );
    } catch (err) {
      const e = err as RelayError;
      dispatch({
        type: "submitErr",
        text:
          `${e.status} FAILED\n\n` +
          (typeof e.body === "string" ? e.body : JSON.stringify(e.body, null, 2)),
      });
    }
  }

  // The account exists before the proxy step, so refresh even when attach fails.
  function refreshCaches() {
    qc.invalidateQueries({ queryKey: ["accounts"] });
    qc.invalidateQueries({ queryKey: ["proxies"] });
    qc.invalidateQueries({ queryKey: ["health-all"] });
  }

  async function attachStep(accountId: string, alreadyBound = false): Promise<boolean> {
    if (!attach) return true;
    let bound = alreadyBound;
    try {
      if (!bound && !(await attach(accountId))) return true;
      bound = true;
      await reloadSession(accountId);
      return true;
    } catch (err) {
      const msg = (err as Error).message;
      dispatch({
        type: "attachErr", accountId, bound,
        text: bound
          ? `Session captured (account ${accountId}) and the proxy is attached, but reloading the session failed:\n` +
            `${msg}\n\nPress Retry to reload it.`
          : `Session captured (account ${accountId}), but proxy attach failed:\n${msg}\n\nPress Retry, or Continue without it.`,
      });
      refreshCaches();
      return false;
    }
  }

  async function finish(accountId: string | null, headline: string) {
    dispatch({ type: "submitOk", text: headline });
    refreshCaches();
    if (accountId) onLinked?.(accountId);
  }

  async function retry() {
    if (!pending) return;
    const { accountId, bound } = pending;
    dispatch({ type: "retryStart" });
    if (await attachStep(accountId, bound)) {
      await finish(accountId, `Proxy attached to account ${accountId}`);
    }
  }

  return (
    <form id={PASTE_FORM_ID} className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (canSubmit(state)) void submit(); }}>
      <ol className="space-y-3 text-[14px] leading-[22px]">
        <li className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <span><span className="text-muted">1.</span> Install the Chatterly Login Capture extension in Chrome.</span>
          {extInstalled === true ? (
            <span className="text-ok">Extension installed</span>
          ) : (
            <a
              href={EXTENSION_URL} target="_blank" rel="noopener noreferrer"
              className="inline-flex h-8 items-center rounded-md border border-border px-[15px] text-fg hover:border-accent hover:text-accent"
            >
              {extInstalled === null ? "Open Chrome Extension" : "Install Chrome Extension"}
            </a>
          )}
        </li>
        <li><span className="text-muted">2.</span> Sign in to OnlyFans in Chrome and open any chat.</li>
        <li><span className="text-muted">3.</span> Open the extension, click Copy cURL and paste it below.</li>
      </ol>

      <div>
        <IfLabel htmlFor="paste-curl-text">Copied cURL</IfLabel>
        <IfTextArea
          id="paste-curl-text"
          rows={5}
          placeholder="curl 'https://onlyfans.com/api2/v2/...' -H 'sign: …' -H 'x-bc: …' -b 'auth_id=…; sess=…; …'"
          value={curl}
          onChange={(e) => dispatch({ type: "setField", field: "curl", value: e.target.value })}
          aria-invalid={!!hint}
          aria-describedby={hint ? "paste-curl-hint" : undefined}
        />
        {hint && (
          <p id="paste-curl-hint" role="status" aria-live="polite" className="mt-1 text-xs text-err leading-relaxed break-words">
            {hint}
          </p>
        )}
        {attach && (
          <IfHelp>
            If this account has no proxy yet, {BRAND_NAME}&apos;s default proxy is assigned after linking, so OnlyFans may
            see it sign in from a new place.
          </IfHelp>
        )}
      </div>

      <details className="text-xs">
        <summary className="cursor-pointer text-muted hover:text-fg">Troubleshooting</summary>
        <IfLabel htmlFor="paste-curl-static" className="mt-2 text-[12px] text-muted">
          static_param override (only for a new OnlyFans revision the extension did not inject one for)
        </IfLabel>
        <IfInput
          id="paste-curl-static"
          placeholder="32 characters; usually leave blank"
          value={staticOverride}
          onChange={(e) => dispatch({ type: "setField", field: "staticOverride", value: e.target.value })}
          className="w-full font-mono"
        />
      </details>

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
          <IfButton variant="primary" onClick={() => void retry()}>Retry</IfButton>
          <IfButton onClick={() => void finish(pending.accountId, continueText(pending))}>
            Continue
          </IfButton>
        </div>
      )}

      {active && (
        <EditorFooter>
          <IfButton type="submit" form={PASTE_FORM_ID} variant="primary" disabled={!canSubmit(state)} className="max-md:hidden">
            {state.busy ? "Linking…" : "Link account"}
          </IfButton>
        </EditorFooter>
      )}
    </form>
  );
}
