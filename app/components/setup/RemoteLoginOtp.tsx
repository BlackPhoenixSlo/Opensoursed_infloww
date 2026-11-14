"use client";

/**
 * The served Browserbase login's 2FA code form (backend: service/remote_login.py; status type and state texts:
 * remoteLogin.ts). Used by BrowserbaseLoginCard (one login) and LoginQueueCard (pasted logins, one job at a time).
 *
 * OtpCodeForm is mounted only while its job is on OnlyFans' 2FA prompt (state "otp"), so leaving or reaching the
 * prompt starts it clean (no stale digits or error). It posts the code to /admin/login/remote/{id}/otp; the job's own
 * thread types it into OnlyFans. The code is never kept past its send.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { relay, RelayError } from "@/lib/relay";
import { IfButton, IfInput, IfLabel } from "@/components/ui/infloww";
import { jobPath, type RemoteLoginStatus } from "@/components/setup/remoteLogin";

/** The relay's messages while the job is on OnlyFans' 2FA prompt (remote_login.OTP_CHECKING / OTP_REJECTED /
 * OTP_NOT_TYPED; the last two matched by prefix). */
const OTP_CHECKING = "checking the 2FA code";
const OTP_REJECTED = "OnlyFans didn't accept that code";
const OTP_NOT_TYPED = "couldn't type the 2FA code";
const OTP_CODE = /^\d{6,8}$/;
/** What the code field keeps of what was typed or pasted: spaces and dashes dropped ("123 456", "1234-5678"), nothing
 *  else changed or cut, so a mistyped or overlong code stays visibly wrong (Submit off) instead of becoming another code. */
const otpInput = (raw: string) => raw.replace(/[\s-]/g, "");

/** The code field for a job on the 2FA prompt; `message` is the job's status message (checking / rejected). */
export function OtpCodeForm({ jobId, message, inputId }: { jobId: string; message: string; inputId: string }) {
  const qc = useQueryClient();
  const [otp, setOtp] = useState("");
  const [otpErr, setOtpErr] = useState<string | null>(null);
  const otpM = useMutation<RemoteLoginStatus, RelayError, string>({
    mutationFn: (code) => relay.post<RemoteLoginStatus>(`${jobPath(jobId)}/otp`, { code }),
    onSuccess: async (job, sent) => {
      setOtpErr(null);
      setOtp((cur) => (cur === sent ? "" : cur));
      // A poll still in flight was read before the code was in: it must not land after this and unlock the field.
      const key = ["remote-login", job.id];
      await qc.cancelQueries({ queryKey: key });
      const cached = qc.getQueryData<RemoteLoginStatus>(key);
      if (!cached || cached.state === "otp") qc.setQueryData(key, job); // a newer poll already past the prompt wins
    },
    onError: (e) => setOtpErr(`Couldn't send the code: ${e.message}`),
  });
  const otpChecking = message === OTP_CHECKING;
  const otpRejected = message.startsWith(OTP_REJECTED);
  const otpNotTyped = message.startsWith(OTP_NOT_TYPED);
  const otpLocked = otpM.isPending || otpChecking; // in flight, or OnlyFans is checking it

  return (
    <form
      className="space-y-2"
      onSubmit={(e) => { e.preventDefault(); if (OTP_CODE.test(otp) && !otpLocked) otpM.mutate(otp); }}
    >
      <IfLabel htmlFor={inputId} className="mb-0">2FA code</IfLabel>
      <div className="flex gap-2">
        <IfInput
          id={inputId} type="text" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]*"
          minLength={6} autoFocus value={otp} placeholder="123456" className="w-40"
          disabled={otpLocked}
          onChange={(e) => setOtp(otpInput(e.target.value))}
        />
        <IfButton type="submit" variant="primary" disabled={!OTP_CODE.test(otp) || otpLocked}>
          {otpM.isPending ? "Sending…" : "Submit code"}
        </IfButton>
      </div>
      {otpChecking && <p className="text-xs text-muted">Checking the code with OnlyFans…</p>}
      {otpRejected && (
        <div role="alert" className="text-err text-sm">
          OnlyFans didn&apos;t accept that code (or hasn&apos;t answered yet). Check it and try again.
        </div>
      )}
      {otpNotTyped && (
        <div role="alert" className="text-err text-sm">
          The code couldn&apos;t be typed into OnlyFans. Try again, or type it in the live view.
        </div>
      )}
      {otpErr && <div role="alert" className="text-err text-sm whitespace-pre-wrap">{otpErr}</div>}
    </form>
  );
}
