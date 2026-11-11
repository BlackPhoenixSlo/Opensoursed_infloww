"use client";

/**
 * PasteCurlCard — the Add creator flow's Extension way in (the fallback when Browser login does not work).
 *
 * Three steps: install the Chatterly Login Capture extension (or see that it is installed), sign in to OnlyFans in
 * Chrome, then click "Copy cURL" in the extension and paste the copy here. We POST it to /admin/session/bootstrap with
 * `mode: 'paste-curl'`. The relay parses cookies + signed headers + the `x-relay-static-param` extension header to
 * derive signing rules for the current OF revision.
 *
 * The proxy is the flow's: `attach` (a new account when the relay has a proxy pool: the pool's automatic pick) runs as
 * the card's attach step after the capture, then the session reloads through it; a line under the box says so (the
 * cookies were minted on this computer's IP). Without `attach` (a row's re-link, or no pool) nothing is bound.
 * "Troubleshooting", folded at the foot: a manual static_param for a brand-new OF revision the extension did not
 * inject one for.
 *
 * Inside the modal (`IfModal footerSlot`) its Link account button sits in the modal's footer, only while `active`.
 * The result panel shows the relay's answer (the new account_id and session file, or the error).
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useReducer } from "react";

import { relay, type BootstrapResponse, RelayError } from "@/lib/relay";
import { accountSessionCaptured } from "@/lib/accountSession";
import { EditorFooter } from "@/components/ui/ifModal";
import { IfButton, IfHelp, IfInput, IfLabel, IfTextArea } from "@/components/ui/infloww";
import { EXTENSION_ID } from "@/components/setup/useExtensionProbe";
import {
  buildBootstrapBody, canSubmit, curlHint, initialPasteCurl, pasteCurlReducer, submitError, type BootstrapBody,
} from "@/components/setup/pasteCurl";

const EXTENSION_URL = `https://chromewebstore.google.com/detail/chatterly-login-capture/${EXTENSION_ID}`;

/** The textarea's form: the footer's Link account submits it. */
const PASTE_FORM_ID = "extension-login-form";

/** `extInstalled` is the page-mount probe's answer (useExtensionProbe): null while checking. The card never probes.
 *  Inside the Add creator flow, `onLinked` hears the new account (when the proxy attach failed, only after Retry
 *  succeeds or Continue is pressed), and the flow's nickname comes in as `initialNickname`. */
export default function PasteCurlCard({ extInstalled, onLinked, initialNickname = "", attach, active = true }: {
  extInstalled: boolean | null;
  onLinked?: (accountId: string) => void;
  initialNickname?: string;
  attach?: (accountId: string) => Promise<void>;
  /** Shown (Link account in the footer); false while the other sign-in is. */
  active?: boolean;
}) {
  const qc = useQueryClient();
  const [state, dispatch] = useReducer(pasteCurlReducer, { nickname: initialNickname }, initialPasteCurl);
  // `pending`: an account captured but whose attach failed. `onLinked` waits for Retry or Continue, so the error
  // stays readable.
  const { curl, staticOverride, result, pending } = state;
  // Why the pasted curl would be refused (no cookies, no user-agent, …), shown under the textarea.
  const hint = curlHint(curl);

  const bootstrapM = useMutation<BootstrapResponse, RelayError, BootstrapBody>({
    mutationFn: (body) => relay.post<BootstrapResponse>("/admin/session/bootstrap", body),
    // Capture already replaced the session, even if proxy attach later fails.
    onSuccess: (data) => { if (data.account_id) accountSessionCaptured(data.account_id); },
  });

  const reloadM = useMutation({
    mutationFn: (account_id: string) =>
      relay.post<unknown>(`/admin/reload-session?account_id=${encodeURIComponent(account_id)}`),
  });

  async function submit() {
    dispatch({ type: "submitStart" });
    const invalid = submitError(state);
    if (invalid) {
      dispatch({ type: "submitErr", text: invalid });
      return;
    }
    try {
      const data = await bootstrapM.mutateAsync(buildBootstrapBody(state));
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

  // Invalidate every cache that depends on accounts/proxies.
  function refreshCaches() {
    qc.invalidateQueries({ queryKey: ["accounts"] });
    qc.invalidateQueries({ queryKey: ["proxies"] });
    qc.invalidateQueries({ queryKey: ["health-all"] });
  }

  /** The attach step: bind the flow's proxy (`attach`), then reload the session. True when there is nothing to attach
   *  or it all worked; on failure the error stays in the card with Retry and Continue. */
  async function attachStep(accountId: string): Promise<boolean> {
    if (!attach) return true;
    let bound = false;
    try {
      await attach(accountId);
      bound = true;
      await reloadM.mutateAsync(accountId);
      return true;
    } catch (err) {
      const msg = (err as Error).message;
      dispatch({
        type: "attachErr", accountId,
        text: bound
          ? `Session captured (account ${accountId}) and the proxy is attached, but reloading the session failed:\n` +
            `${msg}\n\nPress Retry to reload it.`
          : `Session captured (account ${accountId}), but proxy attach failed:\n${msg}\n\nPress Retry, or Continue without it.`,
      });
      // The account was created before the proxy step, so refresh even on the failure path.
      refreshCaches();
      return false;
    }
  }

  /** After the attach step (or Continue past it): clear the curl, report, hand the account on. */
  async function finish(accountId: string | null, headline: string) {
    dispatch({ type: "submitOk", text: headline });
    refreshCaches();
    if (accountId) onLinked?.(accountId);
  }

  async function retry() {
    if (!pending) return;
    const { accountId } = pending;
    dispatch({ type: "retryStart" });
    if (await attachStep(accountId)) {
      await finish(accountId, `Proxy attached to account ${accountId}`);
    }
  }

  return (
    <form id={PASTE_FORM_ID} className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (canSubmit(state) && !bootstrapM.isPending) void submit(); }}>
      <ol className="space-y-3 text-[14px] leading-[22px]">
        <li className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <span><span className="text-muted">1.</span> Install the Chatterly Login Capture extension in Chrome.</span>
          {extInstalled === true ? (
            <span className="text-ok">Extension installed</span>
          ) : (
            // Its text is what desktop/preload.js finds to put "Connect OnlyFans (app)" beside it inside the desktop app.
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
            A proxy is assigned automatically after linking, so OnlyFans may see this account sign in from a new place.
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
          <IfButton variant="primary" onClick={() => void retry()}>Retry</IfButton>
          <IfButton onClick={() => void finish(pending.accountId, `Linked account ${pending.accountId} without a proxy`)}>
            Continue
          </IfButton>
        </div>
      )}

      {active && (
        // No phone: the extension is desktop Chrome's.
        <EditorFooter>
          <IfButton type="submit" form={PASTE_FORM_ID} variant="primary" disabled={!canSubmit(state) || bootstrapM.isPending} className="max-md:hidden">
            {bootstrapM.isPending ? "Linking…" : "Link account"}
          </IfButton>
        </EditorFooter>
      )}
    </form>
  );
}
