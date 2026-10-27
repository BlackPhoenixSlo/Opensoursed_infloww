"use client";

/**
 * FanslyPasteSessionCard — the Fansly analogue of PasteCurlCard.
 *
 * OnlyFans is bootstrapped from a copied cURL; Fansly can't be, because its
 * signing needs the live session blob (token + device id + session id + the
 * exact user-agent), not a replayable request. So the flow is: install the
 * Chatterly Login Capture extension, sign in to Fansly, click
 * "Copy Fansly session," and paste the JSON blob here. We POST it to
 * /admin/session/fansly, which writes the session, probes me() for a name, and
 * registers the account with platform="fansly".
 *
 * The pasted blob is exactly what loginExtensionMulti/fansly_bridge.js copies:
 *   { platform, token, id, accountId, device_id, user_agent,
 *     accept_language, capturedAt, origin }
 * We only forward the fields the relay needs; extras (platform, capturedAt,
 * origin) are ignored.
 *
 * Infloww's Fansly sign-in (`FanslyLogin`, index.9f50f370.js @12411710)
 * words its failures `creators0187` (the bind failed), `creators0416` (the
 * account info read failed, @12412209) and `creators0310` (no Fansly sign-in
 * yet); ours maps a blob that is not a signed-in session to the last, a relay
 * refusal to the first, and a session whose profile read came back empty to
 * the second. Inside the Add creator flow (`formId`) the flow's footer Done
 * submits it, as Infloww's Done does, and the card draws no button of its own.
 *
 * Deliberately simpler than the OF card — no proxy/static_param/onboard
 * machinery is wired on the Fansly side yet (YAGNI: add when asked).
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { relay, type FanslySessionResponse, RelayError } from "@/lib/relay";
import { Button, Card, Input, Textarea } from "@/components/ui/primitives";

/** Infloww's Fansly sign-in strings. */
export const FANSLY_T = {
  loginFailed: "Login failed. Please check your credentials and try again.", //  creators0187
  mustLogIn: "You must be logged in to Fansly to continue", //                 creators0310
  accountInfoError: "An error occurred getting account information", //        creators0416
  /** fansly0003: Infloww's `handleFanslyError` on a 401 (index.9f50f370.js @16347074) before it marks the bind expired. */
  rebind: "Authorization failed, please rebind the account",
} as const;

/** The Add creator flow's Done submits the card through this form id. */
export const FANSLY_FORM_ID = "fansly-session-form";

interface FanslySessionBody {
  token: string;
  id?: string | null;
  accountId: string;
  device_id?: string | null;
  user_agent: string;
  accept_language?: string | null;
  check_key?: string | null;
  nickname?: string;
  make_active?: boolean;
}

/** Inside the Add creator flow, `onLinked` hears the new account, the flow's Nickname comes in as
 *  `initialNickname`, and `formId` lets the flow's Done submit it. */
export default function FanslyPasteSessionCard({ onLinked, initialNickname = "", formId }: {
  onLinked?: (accountId: string) => void;
  initialNickname?: string;
  formId?: string;
} = {}) {
  const qc = useQueryClient();
  const [blob, setBlob] = useState("");
  const [nickname, setNickname] = useState(initialNickname);
  const [makeActive, setMakeActive] = useState(true);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);

  const connectM = useMutation<FanslySessionResponse, RelayError, FanslySessionBody>({
    mutationFn: (body) => relay.post<FanslySessionResponse>("/admin/session/fansly", body),
  });

  async function submit() {
    if (connectM.isPending) return;
    setResult(null);

    let parsed: Record<string, unknown>;
    try {
      // Pre-quote 16+ digit integers so 64-bit snowflake ids (device_id etc.)
      // survive as exact strings instead of being rounded by JSON.parse. (The
      // extension already emits them as strings; this protects hand-pasted or
      // older blobs.) Precision already lost upstream can't be recovered here.
      const safe = blob.replace(/:(\s*)(-?\d{16,})(\s*[,}\]])/g, ':$1"$2"$3');
      parsed = JSON.parse(safe) as Record<string, unknown>;
    } catch {
      setResult({
        ok: false,
        text: `${FANSLY_T.mustLogIn}\n\nThat isn't valid JSON. Paste the whole blob the extension copied (starts with \`{\`).`,
      });
      return;
    }

    // The extension uses camelCase (accountId); tolerate snake_case too.
    const token = (parsed.token ?? "") as string;
    const accountId = (parsed.accountId ?? parsed.account_id ?? "") as string;
    const userAgent = (parsed.user_agent ?? parsed.userAgent ?? "") as string;
    if (!token || !accountId || !userAgent) {
      setResult({
        ok: false,
        text:
          `${FANSLY_T.mustLogIn}\n\nMissing token / accountId / user_agent. Sign in to Fansly in the ` +
          "extension, click Copy Fansly session, then paste again.",
      });
      return;
    }

    // Every id must reach the backend as a string (it types them str; a raw
    // number 422s, as we learned).
    const asId = (v: unknown): string | null =>
      v === null || v === undefined || v === "" ? null : String(v);

    const body: FanslySessionBody = {
      token,
      accountId: String(accountId),
      id: asId(parsed.id),
      device_id: asId(parsed.device_id ?? parsed.deviceId),
      user_agent: userAgent,
      accept_language: asId(parsed.accept_language ?? parsed.acceptLanguage),
      check_key: asId(parsed.check_key ?? parsed.checkKey),
      make_active: makeActive,
    };
    if (nickname.trim()) body.nickname = nickname.trim();

    try {
      const data = await connectM.mutateAsync(body);
      setResult({
        ok: true,
        text:
          `✓ Connected Fansly account ${data.account_id}` +
          (data.name ? ` (${data.name})` : "") +
          `\nPlatform: ${data.platform}` +
          // The relay keeps a session whose me() failed and answers name null.
          (data.name ? "" : `\n${FANSLY_T.accountInfoError}`) +
          `\n\nOpen the inbox — it now reads from Fansly.`,
      });
      setBlob("");
      // Same caches the OF path invalidates, so the account shows up in the
      // switcher / accounts table immediately.
      qc.invalidateQueries({ queryKey: ["accounts"] });
      qc.invalidateQueries({ queryKey: ["health-all"] });
      if (data.account_id) onLinked?.(data.account_id);
    } catch (err) {
      const e = err as RelayError;
      setResult({
        ok: false,
        text:
          `${FANSLY_T.loginFailed}\n\n${e.status} FAILED\n\n` +
          (typeof e.body === "string" ? e.body : JSON.stringify(e.body, null, 2)),
      });
    }
  }

  return (
    <Card>
      <form
        id={formId}
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <div>
          <h2 className="text-base font-semibold mb-1">
            Connect Fansly
            <span className="ml-2 align-middle inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold bg-accent/15 text-accent border border-accent/30">
              Fansly
            </span>
          </h2>
          <p className="text-sm text-fg-dim leading-relaxed mb-3">
            Install the <strong>Chatterly Login Capture</strong> extension, sign in
            to <strong>Fansly</strong>, click <strong>Copy Fansly session</strong>,
            and paste the copied JSON here. Fansly signs each request live, so it
            needs the session blob — not a cURL like OnlyFans.
          </p>
        </div>

        <Textarea
          rows={6}
          placeholder={'{ "platform": "fansly", "token": "…", "id": "…", "accountId": "…", "device_id": "…", "user_agent": "…", "accept_language": "…" }'}
          value={blob}
          onChange={(e) => setBlob(e.target.value)}
          className="font-mono"
        />

        <div>
          <label className="block text-xs text-fg-dim mb-1">Nickname (optional)</label>
          <Input
            placeholder="e.g. Bella-Fansly, Test-burner"
            value={nickname}
            onChange={(e) => setNickname(e.target.value)}
          />
        </div>

        <label className="flex items-center gap-2 text-xs text-fg-dim">
          <input
            type="checkbox"
            checked={makeActive}
            onChange={(e) => setMakeActive(e.target.checked)}
            className="accent-accent"
          />
          Flip this account to the relay&apos;s default after connecting
        </label>

        {formId ? (
          connectM.isPending && <p className="text-xs text-fg-dim">Connecting…</p>
        ) : (
          <Button type="submit" disabled={!blob.trim() || connectM.isPending}>
            {connectM.isPending ? "Connecting…" : "Connect Fansly account"}
          </Button>
        )}

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
      </form>
    </Card>
  );
}
