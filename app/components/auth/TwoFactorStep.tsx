"use client";


import { useEffect, useState } from "react";
import QRCode from "qrcode";

import { CopyButton } from "@/components/ui/CopyButton";
import { errText } from "@/lib/errText";
import { relay } from "@/lib/relay";
import type { SignedInKind, TwoFactorChallenge } from "@/lib/twoFactor";
import { cn } from "@/lib/utils";


interface InitReply { secret: string; otpauth_uri: string; enrol_token: string }
interface ActivateReply { recovery_codes: string[]; kind: SignedInKind }

const TEXT_LINK = "text-sm underline underline-offset-4";
const grouped = (secret: string) => secret.replace(/(.{4})/g, "$1 ").trim();

function SetupQr({ uri }: { uri: string }) {
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    QRCode.toDataURL(uri, { margin: 2, width: 176 }).then((url) => { if (!cancelled) setSrc(url); }, () => {});
    return () => { cancelled = true; };
  }, [uri]);
  if (!src) return null;
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={src} alt="QR code for your authenticator app" width={176} height={176} className="mt-2 rounded-[6px] max-sm:hidden" />;
}

export function BackupCodes({ codes }: { codes: string[] }) {
  return (
    <div>
      <p className="text-sm opacity-80">
        Make a copy of these backup codes that you can enter to authenticate your account when you log in. Each
        works once.
      </p>
      <ul aria-label="Backup codes" className="mt-3 grid grid-cols-1 gap-x-6 sm:grid-cols-2 gap-y-1 font-mono text-sm">
        {codes.map((c) => <li key={c}>{c}</li>)}
      </ul>
      <div className="mt-3"><CopyButton bare text={codes.join("\n")} label="Copy codes" doneLabel="Copied" holdMs={2000}
        className={TEXT_LINK} /></div>
    </div>
  );
}

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
      (err) => { if (!cancelled) setError(errText(err)); },
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
      setError(errText(err));
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
        <p className="text-sm opacity-80">
          Scan the QR code with the app, or on your phone open the link or copy the setup key into the app (time based).
        </p>
        {init ? (
          <>
            <SetupQr uri={init.otpauth_uri} />
            <p aria-label="Setup key" className="mt-2 select-all font-mono text-sm tracking-wider">{grouped(init.secret)}</p>
            <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
              <CopyButton bare text={init.secret} label="Copy setup key" doneLabel="Copied" holdMs={2000}
                className={TEXT_LINK} />
              <a className={TEXT_LINK} href={init.otpauth_uri}>Open in authenticator app</a>
            </div>
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
      setError(errText(err));
      setBusy(false);
    }
  }

  const back = (
    <button type="button" onClick={onCancel} className={cn("mt-6", TEXT_LINK)}>
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
