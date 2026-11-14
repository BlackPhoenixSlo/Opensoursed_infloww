"use client";

/**
 * "Use your own domain": ofl.ink v2's Domain screen (~/oflinkv2/app/editor/screens/domain.js) as an editor card, its
 * copy kept. Three states from the page's one custom domain: none (the "Add domain" form), pending (the records the API
 * answers, "Check now" and "Not yet: …") and live (Open, Copy). "Remove domain" in both, asked first. On top of v2 the
 * status pill shows `pending_cert` (DNS proved, the box's timer getting the certificate). State: `bioDomainForm.ts`.
 */
import { useId, useReducer } from "react";

import { IfButton, IfCard, IfHelp, IfInput, IfLabel, ifButtonClass } from "@/components/ui/infloww";
import { ifConfirm } from "@/components/ui/ifConfirm";
import { CopyButton } from "@/components/growth/_bits";
import {
  bioFailure, useCheckBioDomain, useRemoveBioDomain, useSetBioDomain, type BioDomain, type BioDomainRecord,
  type BioProfile,
} from "@/hooks/useBioPages";
import {
  INITIAL_DOMAIN, bioDomainReducer, buildDomainPayload, domainError, exampleOf, notYet, statusLabel,
} from "@/components/growth/bio/bioDomainForm";
import { cn } from "@/lib/utils";

const PILL: Record<string, string> = {
  pending: "border-warn/40 text-warn", pending_cert: "border-accent/40 text-accent", live: "border-ok/40 text-ok",
};
const OFF = "Custom Domains are not set up on this server yet. Try again later.";

export function BioDomainSection({ profile }: { profile: BioProfile }) {
  const dom = profile.custom_domain;
  const ip = profile.domain_server_ip ?? null;
  const example = exampleOf(profile.username);
  const home = profile.home_url?.replace(/^https?:\/\//, "") ?? null;
  const [form, dispatch] = useReducer(bioDomainReducer, INITIAL_DOMAIN);
  const save = useSetBioDomain(profile.id);
  const check = useCheckBioDomain(profile.id);
  const remove = useRemoveBioDomain(profile.id);
  const id = useId();
  const fail = (fallback: string) => (e: unknown) => dispatch({ type: "failed", msg: bioFailure(e, fallback).msg });

  function submit(e: React.FormEvent) {
    e.preventDefault();
    dispatch({ type: "submit", username: profile.username });
    if (form.busy || domainError(form.draft, profile.username)) return;
    save.mutateAsync(buildDomainPayload(form).domain)
      .then(() => dispatch({ type: "saved" }), fail("The domain was not added. Try again."));
  }
  function runCheck() {
    if (form.busy) return;
    dispatch({ type: "start", op: "check" });
    check.mutateAsync().then((r) => dispatch({ type: "checked", problems: r.check.problems }),
      fail("The check failed. Try again."));
  }
  async function runRemove(d: BioDomain) {
    if (form.busy) return;
    const ok = await ifConfirm(`Remove ${d.domain}?\nVisitors on it will stop seeing this Profile.`,
      { confirmLabel: "Remove domain", danger: true });
    if (!ok) return;
    dispatch({ type: "start", op: "remove" });
    remove.mutateAsync(undefined).then(() => dispatch({ type: "removed", domain: d.domain }),
      fail("The domain was not removed. Try again."));
  }

  const removeButton = dom && (
    <IfButton onClick={() => runRemove(dom)} disabled={form.busy !== null}
      className="border-err/40 text-err hover:border-err hover:text-err">
      {form.busy === "remove" ? "Removing…" : "Remove domain"}
    </IfButton>
  );
  const line = notYet(form);

  return (
    <IfCard title="Use your own domain" data-domain-section>
      <p className="mt-2 text-[13px] text-fg-dim">
        Show @{profile.username} at an address you own, like {example}. You need to be able to change your
        domain&rsquo;s DNS records (where you bought it, or at Cloudflare).
      </p>

      {!ip && dom?.status !== "live" && (
        <div className="mt-3 text-[13px]">
          {dom && <div className="text-fg" data-custom-domain>{`${dom.domain} · ${statusLabel(dom.status)}`}</div>}
          <IfHelp>{OFF}</IfHelp>
        </div>
      )}

      {ip && !dom && (
        <form onSubmit={submit} noValidate className="mt-3">
          <IfLabel htmlFor={`${id}-d`}>Domain</IfLabel>
          <div className="flex flex-wrap items-center gap-2">
            <IfInput id={`${id}-d`} className="min-w-0 flex-1" value={form.draft} inputMode="url"
              placeholder={example} autoComplete="off" autoCapitalize="none" spellCheck={false} maxLength={300}
              aria-invalid={form.error ? true : undefined} aria-describedby={`${id}-h`}
              onChange={(e) => dispatch({ type: "set", draft: e.target.value })} />
            <IfButton type="submit" variant="primary" disabled={form.busy !== null}>
              {form.busy === "save" ? "Adding…" : "Add domain"}
            </IfButton>
          </div>
          <IfHelp id={`${id}-h`}>Without https:// or a slash. Use exactly the address you will put in your bio.</IfHelp>
        </form>
      )}

      {ip && dom && dom.status !== "live" && (
        <div className="mt-4" data-domain-pending>
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-[14px] font-medium text-fg">Point <span data-custom-domain>{dom.domain}</span> here</h3>
            <StatusPill status={dom.status} />
          </div>
          <p id={`${id}-rt`} className="mt-1 text-[13px] text-fg-dim">
            Add these records where your domain&rsquo;s DNS is managed, then press Check now. Changes can take a few
            minutes, sometimes a few hours.
          </p>
          <Records records={dom.records ?? []} labelledBy={`${id}-rt`} />
          <IfHelp>Delete any other A or AAAA record for this name. On Cloudflare, set the cloud to DNS only (grey).</IfHelp>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <IfButton variant="primary" onClick={runCheck} disabled={form.busy !== null}>
              {form.busy === "check" ? "Checking…" : "Check now"}
            </IfButton>
            {removeButton}
          </div>
        </div>
      )}

      {dom && dom.status === "live" && (
        <div className="mt-4" data-domain-live>
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-[14px] font-medium text-fg"><span data-custom-domain>{dom.domain}</span> is live</h3>
            <StatusPill status={dom.status} />
          </div>
          <p className="mt-1 text-[13px] text-fg-dim">
            It shows this Profile now. Put it in your bio.{home && ` ${home} keeps working too.`}
          </p>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <a className={ifButtonClass("primary")} href={`https://${dom.domain}/`} target="_blank" rel="noopener">
              Open
            </a>
            <CopyButton text={`https://${dom.domain}/`} label="Copy" />
            {removeButton}
          </div>
        </div>
      )}

      {line && <p role="status" className="mt-2 text-[13px] text-warn" data-domain-problem>{line}</p>}
      {form.said && <p role="status" className="mt-2 text-[13px] text-ok" data-domain-said>{form.said}</p>}
      {form.error && <p role="alert" className="mt-2 text-[12px] text-err">{form.error}</p>}
      {ip && home && (
        <IfHelp className="mt-4">
          Only want {dom?.domain || example} to forward to {home}? Set up URL forwarding where you bought the domain.
          You don&rsquo;t need to add it here.
        </IfHelp>
      )}
    </IfCard>
  );
}

function StatusPill({ status }: { status: string }) {
  return (
    <span data-domain-status={status}
      className={cn("rounded-full border px-2 py-px text-[12px]", PILL[status] ?? "border-border text-fg-dim")}>
      {statusLabel(status)}
    </span>
  );
}

/** v2's records table: Type, Name, Value; each name and value copyable. */
function Records({ records, labelledBy }: { records: BioDomainRecord[]; labelledBy: string }) {
  return (
    <table className="mt-2 w-full table-fixed text-[13px]" aria-labelledby={labelledBy} data-dns-records>
      <thead>
        <tr className="text-left text-fg-dim">
          <th scope="col" className="w-14 py-1 font-normal">Type</th>
          <th scope="col" className="w-1/3 py-1 font-normal">Name</th>
          <th scope="col" className="py-1 font-normal">Value</th>
        </tr>
      </thead>
      <tbody>
        {records.map((r) => (
          <tr key={`${r.type} ${r.name}`} className="align-middle" data-dns-record={r.type}>
            <th scope="row" className="py-1 text-left font-normal text-fg">{r.type}</th>
            <td className="py-1 pr-2"><Copyable text={r.name} /></td>
            <td className="py-1"><Copyable text={r.value} /></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Copyable({ text }: { text: string }) {
  return (
    <div className="flex min-w-0 items-center gap-1">
      <span className="min-w-0 break-all font-mono text-fg" title={text}>{text}</span>
      <CopyButton text={text} label="Copy" />
    </div>
  );
}
