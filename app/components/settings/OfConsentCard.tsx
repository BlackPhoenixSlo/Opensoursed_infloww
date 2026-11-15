"use client";

/**
 * OfConsentCard — the "Auto-accept OnlyFans consent" checkbox for one Creator
 * (`GET`/`PUT /admin/of-consent/{id}`, hooks/useOfConsent), shown for every
 * Creator (Settings › OnlyFans consent; a plugin's own settings may show it
 * too). While OF wants their consent form (`required`: the consent_required
 * notice) a warning line sits above it. One click saves (no
 * Save bar): while on, every media send for them carries OF's
 * `isConsentAccepted`. The line under it names who changed it last and when.
 * Owner only (a chatter's PUT is 403, shown as the error).
 */
import { TriangleAlert } from "lucide-react";

import { useOfConsent, useSetOfConsent } from "@/hooks/useOfConsent";
import { localWhen } from "@/lib/format";

export function OfConsentCard({ accountId }: { accountId: string }) {
  const q = useOfConsent(accountId);
  const setM = useSetOfConsent();
  const d = q.data;
  if (!d) return null;
  const ch = d.changed;
  return (
    <div data-testid="consent-card" className="rounded-lg border border-border p-3 space-y-1 text-sm">
      {d.required && (
        <p data-testid="consent-warn" role="alert"
          className="flex items-start gap-1.5 text-xs font-medium text-warn">
          <TriangleAlert aria-hidden className="mt-px w-3.5 h-3.5 shrink-0" />
          OnlyFans is rejecting media sends: consent form needed
        </p>
      )}
      <label className="flex items-start gap-2 font-medium text-fg">
        <input type="checkbox" data-testid="consent-box" className="mt-0.5 shrink-0"
          checked={d.auto_accept} disabled={setM.isPending}
          onChange={(e) => setM.mutate({ accountId, autoAccept: e.target.checked })} />
        Auto-accept OnlyFans consent
      </label>
      <p className="text-xs text-fg-dim">
        Use this if OnlyFans rejects media sends with &quot;Consent not accepted&quot; under state
        consent requirements, including North Carolina and Alabama.
        If you aren&apos;t getting consent errors, this setting isn&apos;t needed—you can leave it on or off.
      </p>
      <p className="text-xs text-fg-dim">
        Creator must have signed OF&apos;s consent form (onlyfans.com/my/consent-form). When on, we
        confirm consent on each media send for them.
      </p>
      {ch && (
        <p data-testid="consent-who" className="text-xs text-fg-dim">
          {ch.enabled ? "Turned on" : "Turned off"} by {ch.username ?? "unknown"} · {localWhen(ch.at)}
        </p>
      )}
      {setM.error && <p className="text-xs text-err">{setM.error.message}</p>}
    </div>
  );
}
