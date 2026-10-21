"use client";

/**
 * The pieces Infloww's Creators flows share (Add creator, Edit account details, Edit creator details, Delete creator),
 * rebuilt from the Dashboard bundle (`~/Downloads/infloww-remote-web/index.9f50f370.js`, offsets cited per piece) with
 * the English from Infloww's own en locale chunk (`index.526c4a9d.js`, fetched from the public
 * embed-remote-web.infloww.com asset path and de-obfuscated statically; the key is cited beside each string).
 * "Infloww" in a string reads "Inflowwww", our name.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Camera, Check, CircleCheck, Info, Loader2, Plus, X } from "lucide-react";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";

import { HbModal } from "@/components/ui/infloww";
import { relay, type Employee, type ProxyMeta } from "@/lib/relay";
import { GENDERS, avatarDataUrl, type CreatorDetails, type CreatorProfile, type useCreatorProfiles } from "@/lib/creatorProfiles";
import { cn } from "@/lib/utils";

/** The en locale's strings, by key. */
export const T = {
  addCreator: "Add creator", //                                   leaderboard0002
  linkCreatorAccount: "Link creator account", //                  creators0174
  creatorDetails: "Creator details", //                           creators0076
  displayImage: "Display image", //                               creators0104
  creatorName: "Creator name", //                                 growth0094
  enterName: "Please enter a name", //                            employee0118
  namePattern: "Please input [0-9] or [a-z] or [A-Z]", //         employee0121
  gender: "Gender", //                                            tp-manager0033
  done: "Done", //                                                creators0108
  nextLink: "Next: Link creator account", //                      creators0200
  next: "Next", //                                                growth0251
  newCreatorAdded: "New creator added", //                        creators0195
  whichPlatform: "Which platform’s account would you like to link?", // creators0307
  onePerPlatform: (platform: string) => //                        creators0408
    `Each creator can only link one account from each platform. This creator already has an account from ${platform} linked.`,
  proxySelection: "Proxy selection", //                           creators0240
  proxyRequired: "Using a proxy is required to manage the creator’s account on Inflowwww and allow employees to chat with fans, without revealing the creator’s login information. All your data is safe with us.", // creators0301
  customProxy: "Custom proxy", //                                 router_config_0017
  useOwnProxy: "Use your own proxy", //                           creators0298
  newProxy: "New proxy", //                                       creators0196
  checking: "Loading...", //                                      creators0183 ("Loding...")
  proxyError: "Error message", //                                 creators0121
  connectOnlyFans: "Connect OnlyFans", //                         creators0057
  linkPlatformAccount: (platform: string) => `Link ${platform} account`, // creators0169
  linked: "Creator account is linked to Inflowwww", //            creators0075
  accountDetails: "Account details", //                           creators0021
  nickname: "Nickname", //                                        creators0201
  tagOptional: "Tag (Optional)", //                               creators0276
  tag: "Tag", //                                                  creators0275
  assignedEmployees: "Assigned employees (Optional)", //          creators0041
  selectEmployee: "Select employee", //                           creators0252
  notesOptional: "Internal notes (Optional)", //                  fansly0027
  notesPlaceholder: "Add notes about creator account", //         creators0032
  updateSuccess: "Update Success", //                             creators0296
  stepOf: (i: number, n: number) => `Step ${i} of ${n}`, //       step_of_total
  cancel: "Cancel", //                                            s4s0123
  save: "Save", //                                                tp-manager0055
  editAccountDetails: "Edit account details", //                  creators0112
  editCreatorDetails: "Edit creator details", //                  creators0113
  platform: "Platform", //                                        settings0125
  linkedAccount: "Linked account", //                             creators0181
  connectedAccount: "Connected account", //                       creators0060
  notConnected: "Not connected", //                               creators0202
  disconnected: "Disconnected", //                                creators0103
  linkAccount: "Link account", //                                 creators0172
  unlink: "Unlink", //                                            creators0290
  proxyConnection: "Proxy connection", //                         creators0238
  connection: "Connection", //                                    connection_index (one connection: no index)
  change: "Change", //                                            creators0053
  del: "Delete", //                                               tp-manager0027
  changeProxy: "Change proxy", //                                 creators0054
  switchProxySuccess: "Switch Proxy Success", //                  creators0271
  faceIdTitle: "Face ID Verification", //                         ModalTitleMaps (index.9f50f370.js @12438097)
  selectRoleTitle: "Select your role", //                         ModalTitleMaps
  altMethodTitle: "Linking OnlyFans account (Alternative method)", // ModalTitleMaps
  stillUnable: "Still unable to perform verification and link OnlyFans account to Inflowwww?", // @12434760
  learnMore: "Learn More", //                                     creators0164
  copy: "Copy", //                                                creators0068
  copied: "Copy successfully", //                                 creators0069
  deleteCreator: "Delete creator", //                             creators0097
  submit: "Submit", //                                            employee0173
  back: "Back", //                                                settings0024
  deleteTitle: (creator: string, nickname?: string) => //        delete_creator_title / delete_child_title
    nickname ? `Delete ${creator} / ${nickname}` : `Delete ${creator}`,
  deleteMessage: (creator: string, nickname?: string) => //      delete_creator_step1_message / delete_child_step1_message
    nickname
      ? `All data under ${nickname} will be permanently deleted from Inflowwww. This action cannot be undone.`
      : `All platform accounts and related data under ${creator} will be permanently deleted from Inflowwww. This action cannot be undone.`,
  surveyTitle: "Why are you deleting the creator's account?", //  delete_creator_step2_title
  optional: "Optional", //                                        optional_text
  surveyReasons: [ //                                             delete_survey_reason_1..4, _other
    "Creator is no longer with our agency",
    "Transferred creator to a partner agency",
    "Creator was added for testing purposes only",
    "Migrating creator to another software/CRM/internal solution",
    "Others",
  ],
  surveyOther: "Reason for deleting creator", //                  delete_survey_other_placeholder
  deleted: (name: string) => `${name} deleted`, //               delete_success
} as const;

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

// ── Modal shell: HBModal, `size:"medium",width:600`, `maskClosable:false` ────────────────────────────────────────

/** HB's white text (`element-emphasis-00`), the light theme's ink. */
const HB_WHITE = "text-white [html[data-theme=light]_&]:text-fg";
/** HB's 62% text (`element-emphasis-01`). */
export const HB_DIM = "text-white/[.62] [html[data-theme=light]_&]:text-black/[.62]";

/** The flows' one modal: ticket 00's `HbModal` at 600px (#54: the 24px / 500 title over a hairline, the footer under
 *  one). The mask does not close it; Escape and the × do. */
export function FlowModal({ title, onClose, footer, children, closable = true }: {
  title?: string;
  onClose: () => void;
  footer?: ReactNode;
  children: ReactNode;
  /** `closable:false` modals draw no × and Escape does not close them (Infloww's `closable:false`). */
  closable?: boolean;
}) {
  // The steps read white on the modal (`._content-wrap`: `color:var(--element-emphasis-00)`), not HbModal's 62% body.
  return (
    <HbModal title={title} width={600} onClose={onClose} footer={footer} closable={closable}>
      <div className={cn("text-[14px] leading-normal", HB_WHITE)}>{children}</div>
    </HbModal>
  );
}

/** HBButton at `size:"generous"`: 36px, 8px 12px, 8px corners; `primary` the orange action fill with black text,
 *  `stop` the red signal, else HB's secondary #2c2c2c with white text. */
export function FlowButton({ primary, stop, className, ...p }: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  primary?: boolean; stop?: boolean;
}) {
  return (
    <button
      type="button"
      {...p}
      className={cn(
        "inline-flex h-9 items-center justify-center gap-2 rounded-lg px-3 text-sm font-medium transition-opacity disabled:cursor-not-allowed disabled:opacity-50",
        primary ? "bg-cta text-black hover:opacity-90"
          : stop ? "bg-err text-white hover:opacity-90"
          : cn("bg-[#2c2c2c] hover:bg-[#383838] [html[data-theme=light]_&]:bg-black/[.09]", HB_WHITE),
        className,
      )}
    />
  );
}

/** `StepIndicator` (index.9f50f370.js @12455900): a spacer, then centred the dots (8px apart, the active one white,
 *  the rest `element-emphasis-03`) over "Step N of M" (14px, `element-emphasis-01`), then the button at the right. */
export function StepIndicator({ active, count, children }: { active: number; count: number; children: ReactNode }) {
  return (
    <div className="flex w-full items-center gap-2">
      <div className="flex-1" />
      <div className="flex flex-col items-center gap-2">
        <span aria-hidden className="flex gap-2">
          {Array.from({ length: count }, (_, i) => (
            <span key={i} className={cn("h-2 w-2 rounded-full",
              i === active ? "bg-white [html[data-theme=light]_&]:bg-black" : "bg-white/[.235] [html[data-theme=light]_&]:bg-black/[.235]")} />
          ))}
        </span>
        <span className={cn("text-[14px] leading-4", HB_DIM)}>{T.stepOf(active + 1, count)}</span>
      </div>
      <div className="flex flex-1 items-center justify-end gap-3">{children}</div>
    </div>
  );
}

/** `HBRadioGroup` (index.9fc9db54.css `.hb-radio-group`, `.hb-radio`): a column of items 16px apart, each the 16px
 *  radio 16px before its 16px white label; the radio a 9%-white disc, checked a 4px orange ring around white. */
export const RADIO_GROUP = "flex flex-col gap-4";
export const RADIO_ITEM = cn(
  "flex cursor-pointer items-start gap-4 text-[16px] leading-5 has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-40",
  HB_WHITE,
);
export const RADIO = cn(
  "mt-0.5 h-4 w-4 shrink-0 cursor-pointer appearance-none rounded-full border border-white/[.09] bg-white/[.09] transition-all",
  "hover:bg-white/[.62] checked:border-4 checked:border-cta checked:bg-white checked:hover:bg-white",
  "disabled:cursor-not-allowed",
  "[html[data-theme=light]_&]:border-black/[.09] [html[data-theme=light]_&]:bg-black/[.09]",
  "[html[data-theme=light]_&]:checked:border-cta [html[data-theme=light]_&]:checked:bg-white",
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cta/50",
);
/** A step's title (`._title`: heading4-strong, 20px / 500, 16px under it). */
export const STEP_TITLE = "mb-4 text-[20px] font-medium leading-6";

/** The green check and its line (`HBIconWrapper color:"go"` + `CheckCircleSolid`). */
export function LinkedLine({ text = T.linked }: { text?: string }) {
  return (
    <p className="flex items-center gap-2 text-base font-medium">
      <CircleCheck className="h-5 w-5 text-ok" aria-hidden />
      {text}
    </p>
  );
}

const LABEL = "mb-1 block text-sm font-medium";
/** HB's input at `size:"generous"`: 36px, 8px corners, filled #161616 with no border, #a6a6a6 placeholder. */
export const FIELD = cn(
  "h-9 w-full rounded-lg border-0 bg-[#161616] px-3 text-sm text-white placeholder:text-[#a6a6a6] outline-none",
  "focus-visible:ring-1 focus-visible:ring-border-light [html[data-theme=light]_&]:bg-black/5 [html[data-theme=light]_&]:text-fg",
);

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

/** "infloww" is Infloww's own secure proxy (creators0155); ours is the relay's env pool, one proxy picked at random
 *  and kept per account (docs/proxies.md). "none" is the relay's own server IP; "custom" one of your proxies. */
export type ProxyChoice = { type: "infloww" } | { type: "none" } | { type: "custom"; label: string; ok: boolean | null };

/** GET /admin/proxies: your proxies, and the Inflowwww pool as a count and the accounts on it (never its hosts). */
export interface ProxyList {
  proxies: ProxyMeta[];
  pool: { size: number; account_ids: string[] };
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

export const INFLOWWWW_PROXY = "Inflowwww proxy";
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
            ? "No Inflowwww proxies are set up on this server."
            : "The least-used of Inflowwww's proxies, picked for this account and kept.",
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

/** Puts an account on an Inflowwww proxy: the one it holds, else the least-used (the relay picks). No reload. */
export async function bindPoolProxy(accountId: string) {
  await relay.post("/admin/proxy-pool/assign", { account_id: accountId });
}

/** bindPoolProxy, then reloads the session. */
export async function assignPoolProxy(accountId: string) {
  await bindPoolProxy(accountId);
  await relay.post(`/admin/reload-session?account_id=${encodeURIComponent(accountId)}`);
}

/** Applies a proxy choice to an account: off the old proxy, onto the new one, reload the session. */
export async function applyProxy(accountId: string, current: ProxyChoice, next: ProxyChoice) {
  if (next.type === "infloww") {
    if (current.type !== "infloww") await assignPoolProxy(accountId); // binding moves the account off a custom proxy
    return;
  }
  const oldLabel = current.type === "custom" ? current.label : undefined;
  const nextLabel = next.type === "custom" ? next.label : undefined;
  if (current.type === next.type && oldLabel === nextLabel) return;
  if (current.type === "infloww") await relay.post("/admin/proxy-pool/unbind", { account_id: accountId });
  if (oldLabel) await relay.post(`/admin/proxies/${encodeURIComponent(oldLabel)}/unbind`, { account_id: accountId });
  if (nextLabel) await relay.post("/admin/proxies/assign", { label: nextLabel, account_id: accountId });
  await relay.post(`/admin/reload-session?account_id=${encodeURIComponent(accountId)}`);
}
