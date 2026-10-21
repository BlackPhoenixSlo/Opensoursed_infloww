"use client";

/**
 * AddProxyModal: Custom proxy's "+ Add new proxy" modal, laid out from its Layout capture
 * (`docs/infloww-layouts/creators-proxy.md`, #24 to #36; ticket 18). The capture's fields come first: Proxy label,
 * Type, IP address and Port side by side, Username and Password. The label defaults to `host:port`, as the bulk paste
 * labels its rows, because the relay keys a proxy by its label. That default, the https type, Notes, the storage hint
 * and the bulk paste section are ours, each titled `EXTRA_LABEL`. Presentational: `ProxiesTable` owns the state and
 * the mutations and passes them in, and shows a failed add as its toast (#27; ticket 62).
 */

import { Eye, EyeOff } from "lucide-react";
import { useEffect, useState } from "react";

import { Button, ExtraTag, Input, Textarea } from "@/components/ui/primitives";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";

export type ProxyScheme = "http" | "https" | "socks5";

export interface ProxyDraft {
  /** What the user typed in Proxy label; used only once `labelEdited`. */
  label: string;
  labelEdited: boolean;
  /** #29: none chosen at first. */
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

/** The label the draft saves under: the typed one once edited, else `host:port`. */
export function draftLabel(d: ProxyDraft): string {
  if (d.labelEdited) return d.label;
  const host = d.host.trim();
  return host && d.port ? `${host}:${d.port}` : "";
}

/** The first thing stopping the add, in the form's order, or null. #27 keeps Add proxy off until the form is valid.
 *  `takenLabels` is null until the proxies read lands, and the duplicate guard cannot run before it does. */
export function draftProblem(d: ProxyDraft, takenLabels: readonly string[] | null): string | null {
  const label = draftLabel(d).trim();
  const port = Number(d.port);
  if (!takenLabels) return "not wired: the proxy list has not loaded";
  if (!label) return "Fill in Proxy label";
  if (!d.scheme) return "Choose a Type";
  if (!d.host.trim()) return "Fill in IP address";
  // #32: the bundle's Port takes 0; the Relay refuses it (`service/proxies.py`, "port out of range (1-65535)").
  if (d.port !== "" && port === 0) return "not wired: port 0, as the Relay takes 1–65535";
  if (!d.port || !Number.isInteger(port) || port < 1 || port > 65535) return "Port must be 1–65535";
  if (takenLabels.includes(label)) return `A proxy named "${label}" already exists`;
  return null;
}

export interface BulkResp {
  added: Array<{ label: string; host: string; port: number; scheme: string; username?: string | null }>;
  errors: Array<{ line: number; text_redacted: string; reason: string }>;
}

/** Closes on Escape, as antd's Modal does by default (`keyboard: true`); #24 and #38 leave it on. */
export function useEscape(onClose: () => void) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);
}

/** #35: 32px inputs, 4px 11px, 6px corners; antd dark's #141414 field in a 1px #424242 border (page-parity 03). */
const FIELD_BOX = "bg-[#141414] border border-[#424242] [html[data-theme=light]_&]:bg-white [html[data-theme=light]_&]:border-[#d9d9d9]";
const FIELD_IN = `h-8 py-1 px-[11px] rounded-md ${FIELD_BOX}`;
/** #8's button size, which the capture's footer buttons share; #27: at least 72px. */
const FOOT_BTN = "h-8 py-0 px-[15px] min-w-[72px] rounded text-sm font-normal whitespace-nowrap";

function Field({ id, label, extra, children }: { id?: string; label: string; extra?: boolean; children: React.ReactNode }) {
  // #34: the label 14px above its field, 8px under it; 24px under each field. A group (Type) gets a caption, not a
  // `<label>`, as it has no single control.
  const Caption = id ? "label" : "div";
  return (
    <div className="flex flex-col min-w-0 w-full mb-6">
      <Caption htmlFor={id} className="flex items-center gap-2 pb-2 text-sm">
        {label}
        {extra && <ExtraTag />}
      </Caption>
      {children}
    </div>
  );
}

export default function AddProxyModal({
  draft, onDraft, takenLabels, onSave, saving,
  bulkText, onBulkText, bulkScheme, onBulkScheme, onBulk, bulkPending, bulkError, bulkResult,
  onClose,
}: {
  draft: ProxyDraft;
  onDraft: (d: ProxyDraft) => void;
  takenLabels: readonly string[] | null;
  onSave: () => void;
  saving: boolean;
  bulkText: string;
  onBulkText: (t: string) => void;
  bulkScheme: ProxyScheme;
  onBulkScheme: (s: ProxyScheme) => void;
  onBulk: () => void;
  bulkPending: boolean;
  bulkError: string | null;
  bulkResult: BulkResp | undefined;
  onClose: () => void;
}) {
  const problem = draftProblem(draft, takenLabels);
  const duplicate = problem?.startsWith("A proxy named") ? problem : null;
  const set = (patch: Partial<ProxyDraft>) => onDraft({ ...draft, ...patch });
  const [showPassword, setShowPassword] = useState(false);
  useEscape(onClose);
  return (
    // #26: the mask, rgba(0,0,0,0.7), layer 1000; #24: centred, and a mask click does not close it.
    <div className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/70">
      {/* #24, #25: 800px, at most the window less 32px, 10px corners, no close cross. */}
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="add-proxy-title"
        className="w-[800px] max-w-[calc(100vw-32px)] rounded-[10px] overflow-hidden bg-[#1f1f1f] shadow-xl text-sm [html[data-theme=light]_&]:bg-white"
      >
        {/* #25: the header 22px 24px, the title 16px, weight 600. */}
        <div id="add-proxy-title" className="px-6 py-[22px] text-base font-semibold">Add new proxy</div>

        {/* #25: the body 16px, at most the window less 200px, scrolling. */}
        <div className="p-4 max-h-[calc(100vh-200px)] overflow-auto">
          {/* #28: Proxy label, 32 characters. Its host:port default is ours. */}
          <Field id="add-proxy-label" label="Proxy label">
            <Input
              id="add-proxy-label"
              className={FIELD_IN}
              placeholder="Proxy label"
              maxLength={32}
              value={draftLabel(draft)}
              onChange={(e) => set({ label: e.target.value, labelEdited: true })}
              title={`${EXTRA_LABEL}\nDefaults to host:port, as the bulk paste labels its rows; the relay keys a proxy by its label`}
              autoComplete="off"
              autoFocus
            />
            {duplicate && <span className="pt-1 text-err text-xs">{duplicate}</span>}
          </Field>

          {/* #29, #36: Type radios http and socks (the relay's socks5), none chosen at first; https is ours. */}
          <Field label="Type">
            <div role="radiogroup" aria-label="Type" className="flex flex-wrap items-baseline">
              {([["http", "http"], ["socks5", "socks"], ["https", "https"]] as const).map(([value, word]) => (
                <label
                  key={value}
                  className="inline-flex items-baseline mr-2 cursor-pointer"
                  title={value === "https" ? EXTRA_LABEL : undefined}
                >
                  <input
                    type="radio"
                    name="add-proxy-type"
                    value={value}
                    checked={draft.scheme === value}
                    onChange={() => set({ scheme: value })}
                    className="w-4 h-4 m-0 accent-accent"
                  />
                  <span className="px-2">{word}</span>
                </label>
              ))}
            </div>
          </Field>

          {/* #30 to #32: IP address and Port side by side, 24px apart, each half. */}
          <div className="flex gap-6">
            <Field id="add-proxy-host" label="IP address">
              <Input
                id="add-proxy-host"
                className={FIELD_IN}
                placeholder="IP address"
                value={draft.host}
                onChange={(e) => set({ host: e.target.value })}
                title={`${EXTRA_LABEL}\nAlso takes a hostname, as the relay does`}
                autoComplete="off"
              />
            </Field>
            <Field id="add-proxy-port" label="Port">
              <Input
                id="add-proxy-port"
                className={FIELD_IN}
                placeholder="e.g. 80"
                inputMode="numeric"
                value={draft.port}
                onChange={(e) => set({ port: e.target.value.replace(/[^0-9]/g, "") })}
                autoComplete="off"
              />
            </Field>
          </div>

          {/* #33: Username and Password, both optional. */}
          <Field id="add-proxy-user" label="Username">
            <Input
              id="add-proxy-user"
              className={FIELD_IN}
              placeholder="Username"
              value={draft.username}
              onChange={(e) => set({ username: e.target.value })}
              autoComplete="off"
            />
          </Field>
          {/* #33: Input.Password, its eye at the right reveals the password on demand. */}
          <Field id="add-proxy-pass" label="Password">
            <div className="relative">
              <Input
                id="add-proxy-pass"
                type={showPassword ? "text" : "password"}
                className={`${FIELD_IN} pr-8`}
                placeholder="Password"
                value={draft.password}
                onChange={(e) => set({ password: e.target.value })}
                autoComplete="new-password"
              />
              <button
                type="button"
                aria-label={showPassword ? "Hide password" : "Show password"}
                className="absolute right-[11px] top-1/2 -translate-y-1/2 text-fg-dim hover:text-fg"
                onClick={() => setShowPassword((v) => !v)}
              >
                {showPassword ? <Eye size={14} aria-hidden /> : <EyeOff size={14} aria-hidden />}
              </button>
            </div>
          </Field>
          <Field id="add-proxy-notes" label="Notes" extra>
            <Input
              id="add-proxy-notes"
              className={FIELD_IN}
              placeholder="Notes"
              value={draft.notes}
              onChange={(e) => set({ notes: e.target.value })}
              autoComplete="off"
            />
          </Field>
          <div className="-mt-3 mb-6 text-[11px] text-fg-dim" title={EXTRA_LABEL}>
            {EXTRA_LABEL}: credentials are stored in <code>service/proxies.json</code> in plain text (phase-1).
          </div>

          {/* Ours: the bundle adds one proxy at a time (#42); the relay's bulk add takes one proxy per line. */}
          <section className="border-t border-white/6 pt-4 space-y-2 [html[data-theme=light]_&]:border-[#f0f0f0]" title={EXTRA_LABEL}>
            <div className="flex items-center gap-2">
              <label htmlFor="proxies-bulk" className="block text-sm">
                Paste proxies (one per line)
              </label>
              <ExtraTag />
            </div>
            <Textarea
              id="proxies-bulk"
              rows={4}
              className={`font-mono ${FIELD_BOX}`}
              placeholder={"user:pass@host:port\nhost:port:user:pass"}
              value={bulkText}
              onChange={(e) => onBulkText(e.target.value)}
              autoComplete="off"
              spellCheck={false}
            />
            <div className="flex items-center gap-2">
              <select
                aria-label="Scheme"
                value={bulkScheme}
                onChange={(e) => onBulkScheme(e.target.value as ProxyScheme)}
                className={`${FIELD_BOX} rounded-md px-2 py-1.5 text-sm focus:outline-none focus:border-accent`}
              >
                <option value="http">http</option>
                <option value="https">https</option>
                <option value="socks5">socks5</option>
              </select>
              <Button size="sm" onClick={onBulk} disabled={!bulkText.trim() || bulkPending}>
                {bulkPending ? "Adding…" : "Add all"}
              </Button>
              {bulkError && <span className="text-err text-[11px]">{bulkError}</span>}
            </div>
            {bulkResult && (
              <div className="text-xs space-y-1">
                <div className="text-ok">
                  Added {bulkResult.added.length}
                  {bulkResult.added.length > 0 && `: ${bulkResult.added.map((a) => a.label).join(", ")}`}
                </div>
                {bulkResult.errors.map((e) => (
                  <div key={e.line} className="text-err">
                    Line {e.line}: {e.reason}
                    {e.text_redacted && <span className="font-mono text-fg-dim"> ({e.text_redacted})</span>}
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>

        {/* #27: Cancel, then Add proxy, right-aligned 8px apart, the footer 11px 24px. */}
        <div className="flex items-center justify-end gap-2 px-6 py-[11px]">
          <Button variant="ghost" className={FOOT_BTN} onClick={onClose}>
            Cancel
          </Button>
          <Button
            className={FOOT_BTN}
            onClick={onSave}
            disabled={problem !== null || saving}
            title={saving ? "saving…" : problem ?? undefined}
          >
            Add proxy
          </Button>
        </div>
      </div>
    </div>
  );
}
