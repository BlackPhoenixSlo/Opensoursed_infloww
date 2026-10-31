"use client";

/**
 * The pieces Infloww's Creators flows share (Add creator, Edit account details, Edit creator details, Delete creator),
 * rebuilt from the Dashboard bundle (`~/Downloads/infloww-remote-web/index.9f50f370.js`, offsets cited per piece) with
 * the English from Infloww's own en locale chunk (`index.526c4a9d.js`, fetched from the public
 * embed-remote-web.infloww.com asset path and de-obfuscated statically; the key is cited beside each string).
 * "Infloww" in a string reads "Inflowwww", our name.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Camera, Check, Info, Loader2, Plus, X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import { FIELD, HB_DIM, RADIO, RADIO_GROUP, RADIO_ITEM, STEP_TITLE, T } from "@/components/setup/creatorFlowUi";
import type { ProxyChoice } from "@/components/setup/proxyApi";
import { relay, type Employee, type ProxyMeta } from "@/lib/relay";
import { GENDERS, avatarDataUrl, type CreatorDetails, type CreatorProfile, type useCreatorProfiles } from "@/lib/creatorProfiles";
import { cn } from "@/lib/utils";
import { BRAND_NAME } from "@/lib/brand";

// Split out, re-exported so importers keep `@/components/setup/creatorFlow`.
export {
  FIELD, FlowButton, FlowModal, HB_DIM, LinkedLine, RADIO, RADIO_GROUP, RADIO_ITEM, STEP_TITLE, StepIndicator, T,
} from "@/components/setup/creatorFlowUi";
export { applyProxy, bindPoolProxy, type ProxyChoice } from "@/components/setup/proxyApi";

// ── Toasts (Infloww's `message$4.success` / `showHBSnackbar`) ─────────────────────────────────────────────────────

const TOAST_EVENT = "creators-toast";
export function toast(text: string, tone: "ok" | "err" = "ok") {
  window.dispatchEvent(new CustomEvent(TOAST_EVENT, { detail: { text, tone } }));
}
/** One toast at a time, top centre, 3s (`position:{top:60},duration:3`, index.9f50f370.js @12490079). */
export function CreatorToaster() {
  const [t, setT] = useState<{ text: string; tone: "ok" | "err"; n: number } | null>(null);
  useEffect(() => {
    const on = (e: Event) => setT((p) => ({ ...(e as CustomEvent).detail, n: (p?.n ?? 0) + 1 }));
    window.addEventListener(TOAST_EVENT, on);
    return () => window.removeEventListener(TOAST_EVENT, on);
  }, []);
  useEffect(() => {
    if (!t) return;
    const id = setTimeout(() => setT(null), 3000);
    return () => clearTimeout(id);
  }, [t]);
  if (!t) return null;
  return (
    <div role="status" className={cn(
      "fixed left-1/2 top-[60px] z-[60] -translate-x-1/2 rounded-lg border bg-panel px-4 py-2 text-sm shadow-lg",
      t.tone === "ok" ? "border-ok/40 text-ok" : "border-err/40 text-err",
    )}>
      {t.text}
    </div>
  );
}

const LABEL = "mb-1 block text-sm font-medium";

// ── Creator details: `CreatorsDetailsForm` (index.9f50f370.js @12408534) ─────────────────────────────────────────

const NAME_RE = /^[0-9a-zA-Z_\s一-龥]+$/;
/** The form's rules: name required (trimmed) and of letters, digits, `_` and spaces; gender required. */
export function creatorDetailsError(v: CreatorDetails): string | null {
  if (!v.name.trim()) return T.enterName;
  if (!NAME_RE.test(v.name)) return T.namePattern;
  if (!v.gender) return T.gender;
  return null;
}

export function CreatorsDetailsForm({ value, onChange, showTitle }: {
  value: CreatorDetails;
  onChange: (v: CreatorDetails) => void;
  showTitle?: boolean;
}) {
  const id = useId();
  const file = useRef<HTMLInputElement>(null);
  const [touched, setTouched] = useState(false);
  const set = (p: Partial<CreatorDetails>) => onChange({ ...value, ...p });
  const nameErr = touched ? (!value.name.trim() ? T.enterName : !NAME_RE.test(value.name) ? T.namePattern : null) : null;
  return (
    <div className="space-y-6">
      {showTitle && <p className={cn(STEP_TITLE, "mb-0")}>{T.creatorDetails}</p>}
      <div>
        <span className={LABEL}>{T.displayImage}</span>
        {/* AvatarUpload: a round picker. */}
        <button
          type="button" aria-label={T.displayImage} onClick={() => file.current?.click()}
          className="relative grid h-16 w-16 place-items-center overflow-hidden rounded-full border border-dashed border-white/[.24] bg-[#161616] hover:border-cta [html[data-theme=light]_&]:bg-black/5"
        >
          {value.avatar
            ? <img src={value.avatar} alt="" className="h-full w-full object-cover" />
            : <Camera className="h-5 w-5 text-fg-dim" aria-hidden />}
        </button>
        <input
          ref={file} type="file" accept="image/*" hidden data-testid="avatar-file"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void avatarDataUrl(f).then((avatar) => set({ avatar })).catch(() => toast("not an image", "err"));
            e.target.value = "";
          }}
        />
      </div>
      <div>
        <label htmlFor={`${id}-name`} className={LABEL}>{T.creatorName}</label>
        <input
          id={`${id}-name`} maxLength={50} value={value.name} className={FIELD}
          onChange={(e) => set({ name: e.target.value })} onBlur={() => setTouched(true)}
          aria-invalid={!!nameErr}
        />
        {nameErr && <p className="mt-1 text-xs text-err">{nameErr}</p>}
      </div>
      <div>
        <label htmlFor={`${id}-gender`} className={LABEL}>{T.gender}</label>
        <select id={`${id}-gender`} value={value.gender ?? ""} onChange={(e) => set({ gender: e.target.value as CreatorDetails["gender"] })} className={FIELD}>
          <option value="" disabled hidden />
          {GENDERS.map((g) => <option key={g} value={g}>{g}</option>)}
        </select>
      </div>
    </div>
  );
}

// ── Account details: `EditCreatorForm` (index.9f50f370.js @12470033) ─────────────────────────────────────────────

export interface AccountDetails {
  nickname: string;
  tag: string;
  employeeIds: number[];
  notes: string;
}

/** The Employees a Creator is assigned to: explicit Creator access holding the account. An Employee with access to
 *  every Creator (`account_ids: null`) is assigned already and is shown checked, fixed. */
export const assignedIds = (roster: Employee[] | null, accountId: string) =>
  (roster ?? []).filter((e) => e.account_ids?.includes(accountId)).map((e) => e.id);

export function EditCreatorForm({ value, onChange, tags, roster }: {
  value: AccountDetails;
  onChange: (v: AccountDetails) => void;
  tags: string[];
  /** The active roster; null when the read was refused (Not wired). */
  roster: Employee[] | null;
}) {
  const id = useId();
  const set = (p: Partial<AccountDetails>) => onChange({ ...value, ...p });
  return (
    <div className="space-y-6">
      <div>
        <label htmlFor={`${id}-nick`} className={LABEL}>{T.nickname}</label>
        <input
          id={`${id}-nick`} placeholder={T.nickname} maxLength={50} value={value.nickname} className={FIELD}
          onChange={(e) => set({ nickname: e.target.value })}
        />
      </div>
      <div>
        <label htmlFor={`${id}-tag`} className={LABEL}>{T.tagOptional}</label>
        {/* HBSelect over the agency's Tags with `allowClear`; ours also takes a new Tag typed in (no Tag management
            screen to create one first). */}
        <span className="relative block">
          <input
            id={`${id}-tag`} list={`${id}-tags`} placeholder={T.tag} maxLength={32} value={value.tag} className={FIELD}
            onChange={(e) => set({ tag: e.target.value })}
          />
          {value.tag && (
            <button type="button" aria-label="Clear tag" onClick={() => set({ tag: "" })} className="absolute right-2 top-1/2 -translate-y-1/2 text-fg-dim">
              <X className="h-4 w-4" aria-hidden />
            </button>
          )}
          <datalist id={`${id}-tags`}>{tags.map((t) => <option key={t} value={t} />)}</datalist>
        </span>
      </div>
      <div>
        <span className={LABEL}>{T.assignedEmployees}</span>
        <SelectEmployee value={value.employeeIds} onChange={(employeeIds) => set({ employeeIds })} roster={roster} />
      </div>
      <div>
        <label htmlFor={`${id}-notes`} className={LABEL}>{T.notesOptional}</label>
        <input
          id={`${id}-notes`} placeholder={T.notesPlaceholder} maxLength={64} value={value.notes} className={FIELD}
          onChange={(e) => set({ notes: e.target.value })}
        />
      </div>
    </div>
  );
}

/** `SelectEmployee` (index.9f50f370.js @12468303): Infloww's role cascader, here the active roster as a checklist
 *  with a search box. An Employee who can open every Creator is checked and fixed (change it on Employees). */
function SelectEmployee({ value, onChange, roster }: {
  value: number[]; onChange: (v: number[]) => void; roster: Employee[] | null;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  if (!roster) {
    return <div aria-disabled="true" title="not wired" className={cn(FIELD, "flex items-center opacity-50")}>{T.selectEmployee}</div>;
  }
  const all = roster.filter((e) => e.account_ids == null);
  const names = [...all, ...roster.filter((e) => value.includes(e.id))].map((e) => e.display_name);
  const shown = roster.filter((e) => e.display_name.toLowerCase().includes(q.trim().toLowerCase()));
  return (
    <div className="relative">
      <button
        type="button" aria-label="Assigned employees" aria-haspopup="listbox" aria-expanded={open} onClick={() => setOpen((o) => !o)}
        className={cn(FIELD, "truncate text-left", !names.length && "text-muted")}
      >
        {names.length ? names.join(", ") : T.selectEmployee}
      </button>
      {open && (
        <div role="listbox" aria-label={T.assignedEmployees} aria-multiselectable="true" className="absolute bottom-full z-10 mb-1 max-h-64 w-full overflow-y-auto rounded-lg border border-white/[.09] bg-panel p-1 shadow-lg [html[data-theme=light]_&]:border-black/[.09]">
          <input
            aria-label="Search employees" placeholder={T.selectEmployee} value={q} onChange={(e) => setQ(e.target.value)}
            className="mb-1 h-8 w-full rounded-md border-0 bg-[#161616] px-2 text-sm placeholder:text-[#a6a6a6] focus:outline-none [html[data-theme=light]_&]:bg-black/5"
          />
          {shown.length === 0 && <p className="px-3 py-1.5 text-sm text-fg-dim">No data</p>}
          {shown.map((e) => {
            const fixed = e.account_ids == null;
            const on = fixed || value.includes(e.id);
            return (
              <label key={e.id} title={fixed ? "Can open every Creator (Employees)" : undefined} className={cn("flex items-center gap-2 rounded px-3 py-1.5 text-sm", fixed ? "opacity-60" : "hover:bg-white/[.055]")}>
                <input
                  type="checkbox" role="option" aria-selected={on} checked={on} disabled={fixed} className="accent-cta"
                  onChange={() => onChange(on ? value.filter((x) => x !== e.id) : [...value, e.id])}
                />
                {e.display_name}
                {fixed && <span className="ml-auto text-xs text-fg-dim">All creators</span>}
              </label>
            );
          })}
        </div>
      )}
    </div>
  );
}

/** The active Employees, the ones with a login (`queryEmployeeCascader`), under the table's key; null when refused.
 *  Their Creator access is the enforced one, so assigning one here limits what they see. */
export function useRoster(): Employee[] | null {
  const q = useQuery<{ employees: Employee[] }>({
    queryKey: ["employees", "active"],
    queryFn: () => relay.get<{ employees: Employee[] }>("/admin/employees?include_disabled=false"),
    staleTime: 10_000,
    retry: false,
  });
  return q.error ? null : (q.data?.employees ?? []).filter((e) => !!e.chatter_id);
}

/**
 * Saves the account details (`updateCreator`: nickname, group, employeeIds, description) to what backs each:
 *   nickname   → PATCH /admin/accounts/{id}
 *   employees  → PUT /admin/employees/{eid}/access, for each Employee whose assignment changed (Creator access)
 *   tag, notes → the `creators` profile (useCreatorProfiles), with any Creator details passed along
 */
export function useSaveAccountDetails(profiles: ReturnType<typeof useCreatorProfiles>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ accountId, before, roster, details, creator, draftId }: {
      accountId: string;
      /** The nickname the account had, so an unchanged one sends no PATCH. */
      before: string;
      roster: Employee[] | null;
      details: AccountDetails;
      creator?: Partial<CreatorDetails>;
      draftId?: string;
    }) => {
      const nick = details.nickname.trim();
      if (nick && nick !== before) {
        await relay.patch(`/admin/accounts/${encodeURIComponent(accountId)}`, { nickname: nick });
      }
      for (const e of roster ?? []) {
        if (e.account_ids == null) continue;
        const has = e.account_ids.includes(accountId);
        const want = details.employeeIds.includes(e.id);
        if (has === want) continue;
        const ids = want ? [...e.account_ids, accountId] : e.account_ids.filter((x) => x !== accountId);
        await relay.put(`/admin/employees/${e.id}/access`, { account_ids: ids });
      }
      const profile: CreatorProfile = { ...creator, tag: details.tag.trim() || undefined, notes: details.notes.trim() || undefined };
      if (profiles.wired) await profiles.linkAccount(accountId, profile, draftId);
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["accounts"] });
      void qc.invalidateQueries({ queryKey: ["employees"] });
    },
  });
}

// ── Proxy selection: `SelectProxyUI` (index.9f50f370.js @12426358) ───────────────────────────────────────────────

/** GET /admin/proxies: your proxies, and the Inflowwww pool as a count and the accounts on it (never its hosts);
 *  `bad`: how many pool proxies are unreachable right now (docs/adr/0030). A Creator still on one reads
 *  `proxy_down` in `/admin/accounts`. */
export interface ProxyList {
  proxies: ProxyMeta[];
  pool: { size: number; account_ids: string[]; bad: number };
}
/** `fresh`: refetch on mount even when cached, for a caller that must show the relay's state after a write. */
export function useProxyList(fresh = false) {
  return useQuery<ProxyList>({
    queryKey: ["proxies", "list"],
    queryFn: () => relay.get<ProxyList>("/admin/proxies"),
    staleTime: 60_000,
    refetchOnMount: fresh ? "always" : true,
  });
}

export const INFLOWWWW_PROXY = `${BRAND_NAME} proxy`;
export const NO_PROXY = "No proxy (server IP)";

/** An account's current choice, from the proxy list. */
export function currentProxy(list: ProxyList | undefined, accountId: string): ProxyChoice {
  if (list?.pool?.account_ids.includes(accountId)) return { type: "infloww" };
  const bound = list?.proxies.find((p) => p.assigned_account_ids?.includes(accountId));
  return bound ? { type: "custom", label: bound.label, ok: true } : { type: "none" };
}

/** One line for a choice: the pool by name, a custom proxy by label, scheme and address, else No proxy. */
export function proxyText(choice: ProxyChoice, list?: ProxyList) {
  if (choice.type === "infloww") return INFLOWWWW_PROXY;
  if (choice.type === "none" || !choice.label) return NO_PROXY;
  const p = list?.proxies.find((x) => x.label === choice.label);
  return p ? `${p.label} ${p.scheme} ${p.host}:${p.port}` : choice.label;
}

export function SelectProxyUI({ value, onChange }: { value: ProxyChoice; onChange: (v: ProxyChoice) => void }) {
  const proxiesQ = useProxyList();
  const poolEmpty = !proxiesQ.data?.pool?.size;
  // `checkCustomProxyById` on a pick: our egress-IP check.
  const pick = async (label: string) => {
    onChange({ type: "custom", label, ok: null });
    try {
      const r = await relay.post<{ ok?: boolean }>(`/admin/proxies/${encodeURIComponent(label)}/test`);
      onChange({ type: "custom", label, ok: !!r?.ok });
    } catch {
      onChange({ type: "custom", label, ok: false });
    }
  };
  const radio = (type: ProxyChoice["type"], title: string, desc: string, disabled = false) => (
    <label className={RADIO_ITEM}>
      <input
        type="radio" name="proxy-type" checked={value.type === type} disabled={disabled} className={RADIO}
        onChange={() => onChange(type === "custom" ? { type, label: "", ok: null } : { type })}
      />
      <span className="min-w-0">
        <span className="block">{title}</span>
        <span className={cn("mt-1 block text-[14px] leading-[18px]", HB_DIM)}>{desc}</span>
      </span>
    </label>
  );
  return (
    <div className="space-y-4">
      <div>
        <p className={STEP_TITLE}>{T.proxySelection}</p>
        <p className={cn("-mt-2 text-sm", HB_DIM)}>{T.proxyRequired}</p>
      </div>
      <div role="radiogroup" aria-label={T.proxySelection} className={RADIO_GROUP}>
        {radio(
          "infloww", INFLOWWWW_PROXY,
          poolEmpty && !proxiesQ.isLoading
            ? `No ${BRAND_NAME} proxies are set up on this server.`
            : `The least-used of ${BRAND_NAME}'s proxies, picked for this account and kept.`,
          poolEmpty && value.type !== "infloww",
        )}
        {radio("none", NO_PROXY, "The relay connects from its own server IP; no proxy is used.")}
        {radio("custom", T.customProxy, T.useOwnProxy)}
      </div>
      {value.type === "custom" && (
        <div className="space-y-2">
          <ul aria-label="Proxies" className="max-h-48 overflow-y-auto rounded-lg bg-[#161616] py-1 [html[data-theme=light]_&]:bg-black/5">
            {proxiesQ.isLoading && <li className="px-3 py-2 text-sm text-fg-dim">{T.checking}</li>}
            {proxiesQ.data && proxiesQ.data.proxies.length === 0 && <li className="px-3 py-2 text-sm text-fg-dim">No data</li>}
            {(proxiesQ.data?.proxies ?? []).map((p) => (
              <li key={p.label}>
                <button
                  type="button" aria-pressed={value.label === p.label} onClick={() => void pick(p.label)}
                  className={cn("flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-white/[.055]", value.label === p.label && "bg-white/[.09]")}
                >
                  <span>{proxyText({ type: "custom", label: p.label, ok: null }, proxiesQ.data)}</span>
                  {value.label === p.label && (
                    value.ok === null ? <Loader2 className="h-4 w-4 animate-spin text-fg-dim" aria-label={T.checking} />
                      : value.ok ? <Check className="h-4 w-4 text-[#58A744]" aria-label="Proxy works" />
                      : <span className="flex items-center gap-1 text-xs text-[#FF5C9E]"><Info className="h-4 w-4" aria-hidden />{T.proxyError}</span>
                  )}
                </button>
              </li>
            ))}
          </ul>
          {/* `CreateProxy`: our proxies live on Creators › Custom proxy. */}
          <a href="/creators/proxy" target="_blank" rel="noreferrer" className="inline-flex h-8 items-center gap-1 rounded-lg bg-[#2c2c2c] px-3 text-sm font-medium hover:bg-[#383838] [html[data-theme=light]_&]:bg-black/[.09]">
            <Plus className="h-4 w-4" aria-hidden />{T.newProxy}
          </a>
        </div>
      )}
    </div>
  );
}

/** Whether a choice may go on: a custom proxy only once its check passed (`mn`, index.9f50f370.js @12427600). */
export const proxyChoiceReady = (v: ProxyChoice) => v.type !== "custom" || (!!v.label && v.ok === true);

