"use client";


import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Eye, EyeOff } from "lucide-react";
import { useState } from "react";

import { IfButton, IfHelp, IfInput, IfLabel, IfModal, IfNativeSelect, IfTextArea } from "@/components/ui/infloww";
import { ExtraTag } from "@/components/ui/primitives";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import { relay } from "@/lib/relay";

export type ProxyScheme = "http" | "https" | "socks5";

export interface ProxyDraft {
  label: string;
  labelEdited: boolean;
  scheme: ProxyScheme | "";
  host: string;
  port: string;
  username: string;
  password: string;
  notes: string;
}

export const EMPTY_DRAFT: ProxyDraft = {
  label: "", labelEdited: false, scheme: "", host: "", port: "", username: "", password: "", notes: "",
};

// The relay keys a proxy by its label, hence the host:port default.
export function draftLabel(d: ProxyDraft): string {
  if (d.labelEdited) return d.label;
  const host = d.host.trim();
  return host && d.port ? `${host}:${d.port}` : "";
}

export interface DraftProblem {
  kind: "notWired" | "invalid" | "duplicate";
  text: string;
}

export function draftProblem(d: ProxyDraft, takenLabels: readonly string[] | null): DraftProblem | null {
  const label = draftLabel(d).trim();
  const port = Number(d.port);
  const invalid = (text: string): DraftProblem => ({ kind: "invalid", text });
  if (!takenLabels) return { kind: "notWired", text: "not wired: the proxy list has not loaded" };
  if (!label) return invalid("Fill in Proxy label");
  if (!d.scheme) return invalid("Choose a Type");
  if (!d.host.trim()) return invalid("Fill in IP address");
  if (d.port !== "" && port === 0) return { kind: "notWired", text: "not wired: port 0, as the Relay takes 1–65535" };
  if (!d.port || !Number.isInteger(port) || port < 1 || port > 65535) return invalid("Port must be 1–65535");
  if (takenLabels.includes(label)) return { kind: "duplicate", text: `A proxy named "${label}" already exists` };
  return null;
}

export interface BulkResp {
  added: Array<{ label: string; host: string; port: number; scheme: string; username?: string | null }>;
  errors: Array<{ line: number; text_redacted: string; reason: string }>;
}

function Field({ id, label, extra, children }: { id?: string; label: string; extra?: boolean; children: React.ReactNode }) {
  const caption = <>{label}{extra && <ExtraTag />}</>;
  return (
    <div className="mb-6 flex w-full min-w-0 flex-col">
      {id
        ? <IfLabel htmlFor={id} className="flex items-center gap-2">{caption}</IfLabel>
        : <div className="mb-2 text-[14px] text-fg">{caption}</div>}
      {children}
    </div>
  );
}

export default function AddProxyModal({
  takenLabels, onSave, saving, onClose,
}: {
  takenLabels: readonly string[] | null;
  onSave: (draft: ProxyDraft) => void;
  saving: boolean;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState<ProxyDraft>(EMPTY_DRAFT);
  const problem = draftProblem(draft, takenLabels);
  const duplicate = problem?.kind === "duplicate" ? problem.text : null;
  const set = (patch: Partial<ProxyDraft>) => setDraft({ ...draft, ...patch });
  const [showPassword, setShowPassword] = useState(false);
  return (
    <IfModal
      title="Add new proxy"
      width={800}
      closable={false}
      keyboard
      onClose={onClose}
      footer={
        <>
          <IfButton onClick={onClose}>Cancel</IfButton>
          <IfButton variant="primary" onClick={() => onSave(draft)} disabled={problem !== null || saving}
            title={saving ? "saving…" : problem?.text}>
            Add proxy
          </IfButton>
        </>
      }
    >
      <Field id="add-proxy-label" label="Proxy label">
        <IfInput
          id="add-proxy-label"
          placeholder="Proxy label"
          maxLength={32}
          value={draftLabel(draft)}
          onChange={(e) => set({ label: e.target.value, labelEdited: true })}
          title={`${EXTRA_LABEL}\nDefaults to host:port, as the bulk paste labels its rows; the relay keys a proxy by its label`}
          autoComplete="off"
          autoFocus
        />
        {duplicate && <IfHelp className="text-err">{duplicate}</IfHelp>}
      </Field>

      <Field label="Type">
        <div role="radiogroup" aria-label="Type" className="flex flex-wrap items-center gap-4">
          {([["http", "http"], ["socks5", "socks"], ["https", "https"]] as const).map(([value, word]) => (
            <label key={value} className="inline-flex cursor-pointer items-center gap-2"
              title={value === "https" ? EXTRA_LABEL : undefined}>
              <input
                type="radio"
                name="add-proxy-type"
                value={value}
                checked={draft.scheme === value}
                onChange={() => set({ scheme: value })}
                className="m-0 h-4 w-4 accent-accent"
              />
              {word}
            </label>
          ))}
        </div>
      </Field>

      <div className="flex flex-col sm:flex-row sm:gap-6">
        <Field id="add-proxy-host" label="IP address">
          <IfInput
            id="add-proxy-host"
            placeholder="IP address"
            value={draft.host}
            onChange={(e) => set({ host: e.target.value })}
            title={`${EXTRA_LABEL}\nAlso takes a hostname, as the relay does`}
            autoComplete="off"
          />
        </Field>
        <Field id="add-proxy-port" label="Port">
          <IfInput
            id="add-proxy-port"
            placeholder="e.g. 80"
            inputMode="numeric"
            value={draft.port}
            onChange={(e) => set({ port: e.target.value.replace(/[^0-9]/g, "") })}
            autoComplete="off"
          />
        </Field>
      </div>

      <Field id="add-proxy-user" label="Username">
        <IfInput
          id="add-proxy-user"
          placeholder="Username"
          value={draft.username}
          onChange={(e) => set({ username: e.target.value })}
          autoComplete="off"
        />
      </Field>
      <Field id="add-proxy-pass" label="Password">
        <div className="relative">
          <IfInput
            id="add-proxy-pass"
            type={showPassword ? "text" : "password"}
            className="w-full pr-8"
            placeholder="Password"
            value={draft.password}
            onChange={(e) => set({ password: e.target.value })}
            autoComplete="new-password"
          />
          <button
            type="button"
            aria-label={showPassword ? "Hide password" : "Show password"}
            className="absolute right-[11px] top-1/2 -translate-y-1/2 text-muted hover:text-fg"
            onClick={() => setShowPassword((v) => !v)}
          >
            {showPassword ? <Eye size={14} aria-hidden /> : <EyeOff size={14} aria-hidden />}
          </button>
        </div>
      </Field>
      <Field id="add-proxy-notes" label="Notes" extra>
        <IfInput
          id="add-proxy-notes"
          placeholder="Notes"
          value={draft.notes}
          onChange={(e) => set({ notes: e.target.value })}
          autoComplete="off"
        />
        <IfHelp>
          <span title={EXTRA_LABEL}>Credentials are stored in service/proxies.json in plain text.</span>
        </IfHelp>
      </Field>

      <BulkPaste />
    </IfModal>
  );
}

function BulkPaste() {
  const qc = useQueryClient();
  const [bulkText, setBulkText] = useState("");
  const [bulkScheme, setBulkScheme] = useState<ProxyScheme>("http");
  const bulkM = useMutation({
    // Pasted text carries proxy passwords: read from state here, never a mutation variable (mutations can be persisted).
    mutationFn: () => relay.post<BulkResp>("/admin/proxies/bulk", { text: bulkText, scheme: bulkScheme }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["proxies"] });
      if (r.errors.length === 0) setBulkText("");
    },
  });
  return (
    <section className="border-t border-border pt-6" title={EXTRA_LABEL}>
      <div className="mb-2 flex items-center gap-2">
        <IfLabel htmlFor="proxies-bulk" className="mb-0">Paste proxies (one per line)</IfLabel>
        <ExtraTag />
      </div>
      <IfTextArea
        id="proxies-bulk"
        rows={4}
        placeholder={"user:pass@host:port\nhost:port:user:pass"}
        value={bulkText}
        onChange={(e) => setBulkText(e.target.value)}
        autoComplete="off"
        spellCheck={false}
      />
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <IfNativeSelect
          aria-label="Scheme"
          value={bulkScheme}
          onChange={(e) => setBulkScheme(e.target.value as ProxyScheme)}
        >
          <option value="http">http</option>
          <option value="https">https</option>
          <option value="socks5">socks5</option>
        </IfNativeSelect>
        <IfButton onClick={() => bulkM.mutate()} disabled={!bulkText.trim() || bulkM.isPending}>
          {bulkM.isPending ? "Adding…" : "Add all"}
        </IfButton>
        {bulkM.error && <span className="text-[12px] text-err">{bulkM.error.message}</span>}
      </div>
      {bulkM.data && (
        <div className="mt-2 space-y-1 text-[12px]">
          <div className="text-ok">
            Added {bulkM.data.added.length}
            {bulkM.data.added.length > 0 && `: ${bulkM.data.added.map((a) => a.label).join(", ")}`}
          </div>
          {bulkM.data.errors.map((e) => (
            <div key={e.line} className="text-err">
              Line {e.line}: {e.reason}
              {e.text_redacted && <span className="text-muted"> ({e.text_redacted})</span>}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
