"use client";

/**
 * Security (personal)'s Two-factor authentication and Other sessions cards
 * (service/account_security.py), for whoever is signed in, owner or employee.
 *
 * 2FA: Enable walks through `TwoFactorSetup` in a modal; once on, New backup
 * codes and Disable each ask for a current code. Disable is off while the
 * employee's Agency requires 2FA. Turning 2FA on signs out every other session
 * (the Relay re-issues this one's cookie). Other sessions: "Log out other
 * sessions" ends every session but this one.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { relay } from "@/lib/relay";
import { BackupCodes, TwoFactorSetup } from "@/components/auth/TwoFactorStep";
import { Card, IF_BTN, IF_BTN_PRIMARY } from "@/components/settings/SettingsPanel";
import { IfModal } from "@/components/ui/infloww";

const TIP = "text-[length:var(--if-fs-sm)] leading-5 text-[var(--if-fg-2)]";
const INPUT = "block h-8 w-full rounded-[6px] border border-[var(--if-line)] bg-transparent px-3 text-sm text-[var(--if-fg)]";
const REQUIRED = "Two-factor authentication required by your organization";

interface Status { enabled: boolean; enabled_at: string | null; recovery_codes_left: number; required: boolean }

const STATUS_KEY = ["auth", "2fa"];

/** Disable or New backup codes: a current code (or a backup code), then the action. */
function CodeModal({ action, onClose }: { action: "disable" | "recovery-codes"; onClose: () => void }) {
  const qc = useQueryClient();
  const [code, setCode] = useState("");
  const m = useMutation<{ recovery_codes?: string[] }, Error, string>({
    mutationFn: (c) => relay.post(`/auth/2fa/${action}`, { code: c }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: STATUS_KEY }); if (action === "disable") onClose(); },
  });
  const codes = m.data?.recovery_codes;
  const title = action === "disable" ? "Disable two-factor authentication?" : "New backup codes";
  return (
    <IfModal
      title={title}
      onClose={onClose}
      footer={codes ? (
        <button type="button" className={IF_BTN_PRIMARY} onClick={onClose}>Done</button>
      ) : (
        <>
          <button type="button" className={IF_BTN} onClick={onClose}>Cancel</button>
          <button type="submit" form="two-factor-code-form" className={IF_BTN_PRIMARY} disabled={m.isPending || !code.trim()}>
            {action === "disable" ? "Disable" : "Generate"}
          </button>
        </>
      )}
    >
      {codes ? <BackupCodes codes={codes} /> : (
        <form id="two-factor-code-form" onSubmit={(e) => { e.preventDefault(); m.mutate(code.trim()); }}>
          <label htmlFor="two-factor-current-code" className={TIP}>
            {action === "disable"
              ? "Enter a code from your authentication app to turn two-factor authentication off."
              : "Enter a code from your authentication app. Your old backup codes stop working."}
          </label>
          <input
            id="two-factor-current-code"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            autoComplete="one-time-code"
            autoFocus
            className={`${INPUT} mt-2`}
          />
          {m.error && <p role="alert" className="mt-2 text-sm text-[var(--if-danger)]">{m.error.message}</p>}
        </form>
      )}
    </IfModal>
  );
}

export function TwoFactorCard() {
  const qc = useQueryClient();
  const q = useQuery<Status>({ queryKey: STATUS_KEY, queryFn: () => relay.get<Status>("/auth/2fa") });
  const [modal, setModal] = useState<"setup" | "disable" | "recovery-codes" | null>(null);
  const s = q.data;
  const close = () => setModal(null);
  // Closing setup re-reads the status: 2FA may have gone on before the backup codes' Continue.
  const closeSetup = () => { close(); void qc.invalidateQueries({ queryKey: STATUS_KEY }); };

  const control = !s ? null : s.enabled ? (
    <span className="flex gap-2">
      <button type="button" className={IF_BTN} onClick={() => setModal("recovery-codes")}>New backup codes</button>
      <button
        type="button"
        className={IF_BTN}
        disabled={s.required}
        title={s.required ? REQUIRED : undefined}
        onClick={() => setModal("disable")}
      >
        Disable
      </button>
    </span>
  ) : (
    <button type="button" className={IF_BTN} onClick={() => setModal("setup")}>Enable 2FA</button>
  );

  return (
    <Card title="Two-factor authentication" control={control}>
      <p className={TIP}>
        {q.error ? q.error.message : !s ? "…" : s.enabled
          ? `Enabled on ${new Date(s.enabled_at ?? "").toLocaleDateString()}. ${s.recovery_codes_left} backup codes left.`
          : s.required
            ? `${REQUIRED}. Set it up to keep signing in.`
            : "Sign in with a code from an authenticator app as well as your password."}
      </p>
      {modal === "setup" && (
        <IfModal title="Set up two-factor authentication" onClose={closeSetup} width={560}>
          <TwoFactorSetup inputClass={INPUT} buttonClass={IF_BTN_PRIMARY} onDone={closeSetup} />
        </IfModal>
      )}
      {(modal === "disable" || modal === "recovery-codes") && <CodeModal action={modal} onClose={close} />}
    </Card>
  );
}

export function OtherSessionsCard() {
  const m = useMutation({ mutationFn: () => relay.post("/auth/sessions/revoke-others", {}) });
  return (
    <Card
      title="Other sessions"
      control={
        <button type="button" className={IF_BTN} disabled={m.isPending} onClick={() => m.mutate()}>
          Log out other sessions
        </button>
      }
    >
      <p className={TIP}>
        {m.isSuccess
          ? "Every other session is signed out. This one stays signed in."
          : m.error
            ? m.error.message
            : "Sign out of this account on every other browser and device."}
      </p>
    </Card>
  );
}
