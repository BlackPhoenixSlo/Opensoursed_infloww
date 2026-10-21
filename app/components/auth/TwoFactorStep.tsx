"use client";

/**
 * TwoFactorStep: sign-in's second step (service/account_security_api.py), in place
 * of the password form once the Relay answers with a `TwoFactorChallenge`.
 * "verify" asks for a code from the authenticator app (or a backup code);
 * "setup" is the Agency requiring 2FA of a login that has none, so it walks
 * through `TwoFactorSetup` first. Either way the Relay sets the session cookie
 * on success and the caller hard-navigates, as a chatter sign-in does.
 *
 * `TwoFactorSetup` is also Security (personal)'s "Enable 2FA". There is no QR
 * code (the app has no QR library): the setup key is shown to type in, and the
 * otpauth:// link opens the authenticator app on a phone. Copy is Infloww's.
 */

import { useEffect, useState } from "react";

import { relay } from "@/lib/relay";
import type { SignedInKind, TwoFactorChallenge } from "@/lib/twoFactor";
import { cn } from "@/lib/utils";


interface InitReply { secret: string; otpauth_uri: string; enrol_token: string }
interface ActivateReply { recovery_codes: string[]; kind: SignedInKind }

const message = (err: unknown) => (err instanceof Error ? err.message : String(err));

/** The setup key in fours, as authenticator apps print it. */
const grouped = (secret: string) => secret.replace(/(.{4})/g, "$1 ").trim();

export function BackupCodes({ codes }: { codes: string[] }) {
  const [copied, setCopied] = useState(false);
  return (
    <div>
      <p className="text-sm opacity-80">
        Make a copy of these backup codes that you can enter to authenticate your account when you log in. Each
        works once.
      </p>
      <ul aria-label="Backup codes" className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1 font-mono text-sm">
        {codes.map((c) => <li key={c}>{c}</li>)}
      </ul>
      <button
        type="button"
        className="mt-3 text-sm underline underline-offset-4"
        onClick={() => {
          void navigator.clipboard?.writeText(codes.join("\n")).then(() => setCopied(true), () => {});
        }}
      >
        {copied ? "Copied" : "Copy codes"}
      </button>
    </div>
  );
}

/** Set up 2FA: the key, then a code to prove the app has it, then the backup codes. `ticket` is a sign-in
 *  ticket (no session yet); without one it is the signed-in principal's own setup. */
export function TwoFactorSetup({ ticket, inputClass, buttonClass, onDone }: {
  ticket?: string;
  inputClass: string;
  buttonClass: string;
  onDone: (kind: SignedInKind) => void;
}) {
  const [init, setInit] = useState<InitReply | null>(null);
  const [done, setDone] = useState<ActivateReply | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    relay.post<InitReply>("/auth/2fa/init", ticket ? { ticket } : {}).then(
      (r) => { if (!cancelled) setInit(r); },
      (err) => { if (!cancelled) setError(message(err)); },
    );
    return () => { cancelled = true; };
  }, [ticket]);

  async function activate(e: React.FormEvent) {
    e.preventDefault();
    if (!init || busy) return;
    setBusy(true);
    setError(null);
    try {
      setDone(await relay.post<ActivateReply>("/auth/2fa/activate", {
        enrol_token: init.enrol_token, code: code.trim(), ...(ticket ? { ticket } : {}),
      }));
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <div>
        <p className="font-medium">Two-factor authentication is now active on your account</p>
        <div className="mt-4"><BackupCodes codes={done.recovery_codes} /></div>
        <button type="button" className={cn(buttonClass, "mt-6")} onClick={() => onDone(done.kind)}>Continue</button>
      </div>
    );
  }

  return (
    <form onSubmit={activate} className="flex flex-col gap-4">
      <div>
        <p className="font-medium">Step 1. Get an authenticator app</p>
        <p className="text-sm opacity-80">Google Authenticator, Microsoft Authenticator, 1Password or any TOTP app.</p>
      </div>
      <div>
        <p className="font-medium">Step 2. Add your account to the app</p>
        <p className="text-sm opacity-80">Enter this setup key in the app (time based), or open the link on your phone.</p>
        {init ? (
          <>
            <p aria-label="Setup key" className="mt-2 select-all font-mono text-sm tracking-wider">{grouped(init.secret)}</p>
            <a className="text-sm underline underline-offset-4" href={init.otpauth_uri}>Open in authenticator app</a>
          </>
        ) : !error && <p className="mt-2 text-sm opacity-60">…</p>}
      </div>
      <div>
        <label htmlFor="two-factor-setup-code" className="font-medium">Step 3. Enter verification code</label>
        <input
          id="two-factor-setup-code"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          placeholder="Enter the 6-digit code from your authentication app"
          inputMode="numeric"
          autoComplete="one-time-code"
          required
          className={cn(inputClass, "mt-2")}
        />
      </div>
      {error && <p role="alert" className="text-sm text-[#fb609f]">{error}</p>}
      <button type="submit" disabled={!init || busy} className={buttonClass}>
        {busy ? "…" : "Verify code and activate"}
      </button>
    </form>
  );
}

/** The sign-in forms' second step, in their site look. */
export default function TwoFactorStep({ challenge, inputClass, buttonClass, onSignedIn, onCancel }: {
  challenge: TwoFactorChallenge;
  inputClass: string;
  buttonClass: string;
  onSignedIn: (kind: SignedInKind) => void;
  onCancel: () => void;
}) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function verify(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const r = await relay.post<{ kind: SignedInKind }>("/auth/2fa/login", { ticket: challenge.ticket, code: code.trim() });
      onSignedIn(r.kind);
    } catch (err) {
      setError(message(err));
      setBusy(false);
    }
  }

  const back = (
    <button type="button" onClick={onCancel} className="mt-6 text-sm underline underline-offset-4">
      Sign in with another account
    </button>
  );

  if (challenge.two_factor === "setup") {
    return (
      <section aria-labelledby="two-factor-title">
        <h2 id="two-factor-title" className="text-xl font-medium">Set up two-factor authentication</h2>
        <p className="mt-2 mb-6 text-sm opacity-80">
          Two-factor authentication required by your organization. Set it up to sign in as {challenge.username}.
        </p>
        <TwoFactorSetup ticket={challenge.ticket} inputClass={inputClass} buttonClass={buttonClass} onDone={onSignedIn} />
        {back}
      </section>
    );
  }

  return (
    <section aria-labelledby="two-factor-title">
      <h2 id="two-factor-title" className="text-xl font-medium">Two-factor authentication</h2>
      <form onSubmit={verify} className="mt-4 flex flex-col gap-4">
        <div>
          <label htmlFor="two-factor-code" className="block text-base font-medium">Verification code</label>
          <input
            id="two-factor-code"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder="Enter the 6-digit code from your authentication app"
            inputMode="text"
            autoComplete="one-time-code"
            autoFocus
            required
            className={cn(inputClass, "mt-2")}
          />
          <p className="mt-2 text-sm opacity-70">Lost your phone? Enter one of your backup codes instead.</p>
        </div>
        {error && <p role="alert" className="text-sm text-[#fb609f]">{error}</p>}
        <button type="submit" disabled={busy} className={buttonClass}>{busy ? "…" : "Verify"}</button>
      </form>
      {back}
    </section>
  );
}
