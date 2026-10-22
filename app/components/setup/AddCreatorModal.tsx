"use client";

/**
 * AddCreatorModal — Infloww's Add creator / Link creator account modal (docs/infloww-layouts/creators-manage.md #54
 * to #76), step for step from the Dashboard bundle (`AddCreatorsModal`, index.9f50f370.js), with Infloww's
 * English (creatorFlow.tsx's `T`):
 *
 *   creators-details  "Creator details": Display image, Creator name, Gender. Done saves the Creator and closes;
 *                     "Next: Link creator account" saves it and goes on. Both say "New creator added".
 *   select-platform   OnlyFans or Fansly; a platform the Creator already has an account on is disabled.
 *   select-proxy      OnlyFans only, step 1 of 3: Inflowwww proxy (the relay's pool; the default when it has one, else
 *                     No proxy), No proxy or a custom proxy whose check passed; "Connect OnlyFans".
 *   login             Infloww's embedded OnlyFans sign-in (`OfLogin`) is ours: Paste cURL (the browser extension) and
 *                     Try Browserbase login (a remote browser on Browserbase's network, a human solving any challenge),
 *                     Inflowwww extras, preset with the flow's Creator name and Proxy selection, which both bind after
 *                     the capture (under Inflowwww proxy Paste cURL has no proxy select, and its attach step binds a
 *                     pool proxy; the Browserbase job binds the same on the relay). On a phone only Browserbase login
 *                     shows (no extension there), with a line saying Paste cURL is desktop-only. Fansly's is the
 *                     Fansly paste session, desktop-only. "Still unable…" opens Infloww's Select your role and
 *                     Alternative method screens.
 *   linked            "Creator account is linked to Inflowwww": the account and the proxy the relay has it on (read
 *                     back from GET /admin/proxies, not the radio picked); step 2 of 3.
 *   creator-details   "Account details": Nickname, Tag, Assigned employees, Internal notes; step 3 of 3. Saved to the
 *                     account (nickname), Creator access (employees) and the `creators` profile (useCreatorProfiles).
 *   success           "Creator account is linked to Inflowwww", Done.
 *
 * Not drawn: the second-proxy offer, which the bundle switches off (#76, `const Mt=false`); Infloww's Face ID
 * Verification screen, which its embedded browser raises on OnlyFans' Face ID page, a page our sign-in does not reach.
 *
 * Entry points: the header's Add creator (step 1); a Creator row with no account, "Link creator account" (`draft`, at
 * select-platform); a row's "Link another account" (`linkAnother`, at select-platform, its platforms disabled); a
 * row's recovery actions (`at`, straight to the sign-in section that performs it, and Done once linked).
 */

import { ExternalLink, UserPlus } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import PasteCurlCard from "@/components/setup/PasteCurlCard";
import BrowserbaseLoginCard from "@/components/setup/BrowserbaseLoginCard";
import FanslyPasteSessionCard, { FANSLY_FORM_ID, FANSLY_T } from "@/components/setup/FanslyPasteSessionCard";
import {
  CreatorsDetailsForm, EditCreatorForm, FlowButton, FlowModal, HB_DIM, LinkedLine, RADIO, RADIO_GROUP, RADIO_ITEM,
  STEP_TITLE, SelectProxyUI, StepIndicator, T,
  assignedIds, bindPoolProxy, creatorDetailsError, currentProxy, proxyChoiceReady, proxyText, toast, useProxyList,
  useRoster, useSaveAccountDetails, type AccountDetails, type ProxyChoice,
} from "@/components/setup/creatorFlow";
import { PlatformLogo } from "@/components/shell/PlatformSwitcher";
import { HbButton } from "@/components/ui/infloww";
import { pickAvatarUrl, useAccountAvatar } from "@/hooks/useAccountAvatar";
import { useCreatorProfiles, type CreatorDetails, type DraftCreator } from "@/lib/creatorProfiles";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import { cn } from "@/lib/utils";

/** The page's one line for phones (spec, Mobile). */
export const DESKTOP_ONLY_LINE = "Paste cURL (the browser extension) and keys are desktop-only. On a phone, link a creator with Browserbase login.";
/** The OnlyFans sign-in's line for phones, under the Browserbase card. */
export const MOBILE_PASTE_LINE = "Paste cURL needs the desktop browser extension.";
/** The Fansly sign-in's line for phones. */
export const MOBILE_FANSLY_LINE = "The Fansly paste session is desktop-only.";

/** Our sign-in sections. */
const SECTIONS = {
  paste: { id: "add-creator-paste-curl", name: "Paste cURL" },
  browserbase: { id: "add-creator-browserbase", name: "Browserbase login" },
  fansly: { id: "add-creator-fansly", name: "Fansly paste session" },
} as const;
export type SectionKey = keyof typeof SECTIONS;

export type Platform = "onlyfans" | "fansly";
export const PLATFORM_LABEL: Record<Platform, string> = { onlyfans: "OnlyFans", fansly: "Fansly" };

function Section({ k, children }: { k: SectionKey; children: ReactNode }) {
  const s = SECTIONS[k];
  return (
    <section id={s.id} aria-label={s.name} title={EXTRA_LABEL} tabIndex={-1} className="space-y-2 focus:outline-none">
      <p className="text-xs text-muted">{EXTRA_LABEL}</p>
      {children}
    </section>
  );
}

/** Every step after the first, and a row's entry points, read `creators0174`. */
export const ROW_LINK_TITLE = T.linkCreatorAccount;

type Step = "creators-details" | "select-platform" | "select-proxy" | "login" | "role" | "alt" | "linked" | "creator-details" | "success";

export default function AddCreatorModal({ extInstalled, onClose, at, draft, linkAnother }: {
  extInstalled: boolean | null;
  onClose: () => void;
  /** A row's recovery action: straight to the sign-in section that performs it. */
  at?: SectionKey;
  /** A Creator saved with Done and not linked yet: its details, at select-platform. */
  draft?: DraftCreator;
  /** "Link another account": the Creator's details and the platforms it has an account on. */
  linkAnother?: { creator: CreatorDetails; linked: Platform[] };
}) {
  const profiles = useCreatorProfiles();
  const roster = useRoster();
  const save = useSaveAccountDetails(profiles);
  const [step, setStep] = useState<Step>(at ? "login" : draft || linkAnother ? "select-platform" : "creators-details");
  const [details, setDetails] = useState<CreatorDetails>(draft ?? linkAnother?.creator ?? { name: "", gender: "" });
  const [draftId, setDraftId] = useState<string | undefined>(draft?.id);
  const taken = linkAnother?.linked ?? [];
  const [platform, setPlatform] = useState<Platform>(at === "fansly" ? "fansly" : taken.includes("onlyfans") ? "fansly" : "onlyfans");
  // The Proxy selection: the Inflowwww proxy by default when the relay has a pool, else No proxy. A row's recovery
  // (`at`) skips the step and binds nothing, so the account keeps the proxy it is on.
  const proxiesQ = useProxyList();
  const [picked, setProxy] = useState<ProxyChoice | null>(at ? { type: "none" } : null);
  const proxy: ProxyChoice = picked ?? (proxiesQ.data?.pool?.size ? { type: "infloww" } : { type: "none" });
  const [accountId, setAccountId] = useState<string | null>(null);
  const [account, setAccount] = useState<AccountDetails | null>(null);
  const [busy, setBusy] = useState(false);
  const of = platform === "onlyfans";
  const count = of ? 3 : 2;

  useEffect(() => {
    if (!at) return;
    const el = document.getElementById(SECTIONS[at].id);
    el?.scrollIntoView?.({ block: "start" });
    el?.focus();
  }, [at]);

  // Done / Next on step 1 (`addCreators`): the Creator is saved before any account.
  const saveDetails = async (then: () => void) => {
    setBusy(true);
    try {
      if (draftId) await profiles.updateDraft(draftId, details);
      else setDraftId((await profiles.addDraft(details)).id);
      toast(T.newCreatorAdded);
      then();
    } catch (e) {
      toast((e as Error).message, "err");
    } finally {
      setBusy(false);
    }
  };

  const linked = (id: string) => {
    setAccountId(id);
    setAccount({ nickname: details.name, tag: profiles.profiles[id]?.tag ?? "", employeeIds: assignedIds(roster, id), notes: profiles.profiles[id]?.notes ?? "" });
    setStep("linked");
  };

  const detailsErr = creatorDetailsError(details);
  const title = step === "creators-details" ? T.addCreator : ROW_LINK_TITLE;
  const proxyLabel = proxy.type === "custom" ? proxy.label : "";

  let body: ReactNode;
  let footer: ReactNode;
  switch (step) {
    case "creators-details":
      body = <CreatorsDetailsForm value={details} onChange={setDetails} showTitle />;
      footer = (
        <>
          <FlowButton
            disabled={!!detailsErr || busy || !profiles.wired} title={!profiles.wired ? "not wired" : undefined}
            onClick={() => void saveDetails(onClose)}
          >
            {T.done}
          </FlowButton>
          <FlowButton
            primary disabled={!!detailsErr || busy}
            // A chatter cannot save a Creator; the flow still links the account.
            onClick={() => (profiles.wired ? void saveDetails(() => setStep("select-platform")) : setStep("select-platform"))}
          >
            {T.nextLink}
          </FlowButton>
        </>
      );
      break;
    case "select-platform":
      body = (
        <div className="space-y-4">
          <p className={STEP_TITLE}>{T.whichPlatform}</p>
          <div role="radiogroup" aria-label="Platform" className={RADIO_GROUP}>
            {(["onlyfans", "fansly"] as const).map((p) => {
              const off = taken.includes(p);
              return (
                <label
                  key={p} title={off ? T.onePerPlatform(PLATFORM_LABEL[p]) : undefined}
                  className={cn(RADIO_ITEM, "items-center")}
                >
                  <input type="radio" name="platform" checked={platform === p} disabled={off} onChange={() => setPlatform(p)} className={cn(RADIO, "mt-0")} />
                  {/* `HBIconWrapper size:"intermediate"` with the platform's mark, the label 4px after it (#63). */}
                  <span className="flex items-center gap-1"><PlatformLogo platform={p} />{PLATFORM_LABEL[p]}</span>
                </label>
              );
            })}
          </div>
        </div>
      );
      footer = (
        <FlowButton primary disabled={taken.includes(platform)} onClick={() => setStep(of ? "select-proxy" : "login")}>
          {T.next}
        </FlowButton>
      );
      break;
    case "select-proxy":
      body = <SelectProxyUI value={proxy} onChange={setProxy} />;
      footer = (
        <StepIndicator active={0} count={3}>
          <FlowButton primary disabled={!proxyChoiceReady(proxy)} onClick={() => setStep("login")}>{T.connectOnlyFans}</FlowButton>
        </StepIndicator>
      );
      break;
    case "login":
      body = (
        <div className="space-y-4">
          <p className={STEP_TITLE}>{T.linkPlatformAccount(PLATFORM_LABEL[platform])}</p>
          {of ? (
            <div className="space-y-6">
              {/* No extension on a phone: Paste cURL is desktop-only, and Browserbase login is the step's content. */}
              <div className="hidden md:block">
                <Section k="paste">
                  <PasteCurlCard
                    extInstalled={extInstalled} onLinked={linked} initialNickname={at ? "" : details.name} initialProxyLabel={proxyLabel}
                    attach={proxy.type === "infloww" ? bindPoolProxy : undefined}
                  />
                </Section>
              </div>
              <Section k="browserbase">
                <BrowserbaseLoginCard onLinked={linked} initialNickname={at ? "" : details.name} proxy={at ? undefined : proxy} />
              </Section>
              <p className="md:hidden text-sm text-fg-dim" title={EXTRA_LABEL}>{MOBILE_PASTE_LINE}</p>
              <button type="button" onClick={() => setStep("role")} className="text-sm text-cta hover:underline">
                {T.stillUnable}
              </button>
            </div>
          ) : (
            <>
              <p className="md:hidden text-sm text-fg-dim" title={EXTRA_LABEL}>{MOBILE_FANSLY_LINE}</p>
              <div className="hidden md:block">
                <Section k="fansly"><FanslyPasteSessionCard onLinked={linked} initialNickname={at ? "" : details.name} formId={FANSLY_FORM_ID} /></Section>
              </div>
            </>
          )}
        </div>
      );
      footer = at ? <FlowButton onClick={onClose}>{T.cancel}</FlowButton> : (
        <FlowButton onClick={() => setStep(of ? "select-proxy" : "select-platform")}>{T.cancel}</FlowButton>
      );
      // OnlyFans: the sign-in is step 1's second half (the proxy's "Connect OnlyFans" opens it, #68), so it keeps the
      // proxy step's dots. Fansly counts from linked (`dotCount:2`); its sign-in comes before step 1 and has none.
      if (of && !at) footer = <StepIndicator active={0} count={3}>{footer}</StepIndicator>;
      // Infloww's Fansly sign-in: Done beside Cancel submits the session (`creators0108`, @12411710).
      if (!of) footer = <>{footer}<FlowButton primary type="submit" form={FANSLY_FORM_ID}>{T.done}</FlowButton></>;
      break;
    case "role":
      body = <SelectRole onAdmin={() => setStep("alt")} onCreator={() => setStep("login")} onCancel={() => setStep("login")} />;
      footer = null;
      break;
    case "alt":
      body = <AlternativeMethod />;
      footer = <FlowButton onClick={() => setStep("login")}>{T.back}</FlowButton>;
      break;
    case "linked":
      body = <LinkedAccount accountId={accountId!} platform={platform} />;
      footer = at ? <FlowButton primary onClick={onClose}>{T.done}</FlowButton> : (
        <StepIndicator active={of ? 1 : 0} count={count}>
          <FlowButton primary onClick={() => setStep("creator-details")}>{T.next}</FlowButton>
        </StepIndicator>
      );
      break;
    case "creator-details":
      body = (
        <div className="space-y-4">
          <p className={STEP_TITLE}>{T.accountDetails}</p>
          <EditCreatorForm value={account!} onChange={setAccount} tags={profiles.tags} roster={roster} />
        </div>
      );
      footer = (
        <StepIndicator active={of ? 2 : 1} count={count}>
          <FlowButton
            primary disabled={!account?.nickname.trim() || save.isPending}
            onClick={() => save.mutate(
              { accountId: accountId!, before: "", roster, details: account!, creator: details, draftId },
              {
                onSuccess: () => { toast(T.updateSuccess); setStep("success"); },
                onError: (e) => toast((e as Error).message, "err"),
              },
            )}
          >
            {T.next}
          </FlowButton>
        </StepIndicator>
      );
      break;
    case "success":
      body = <LinkedLine />;
      footer = <FlowButton primary onClick={onClose}>{T.done}</FlowButton>;
      break;
  }

  return <FlowModal title={title} onClose={onClose} footer={footer}>{body}</FlowModal>;
}

/** The linked step's account: avatar, name, @username (Fansly: fansly.com/username, read through the relay's Fansly
 *  shim, and Infloww's `creators0416` when that read fails), and the proxy the relay has it on (refetched, so a failed
 *  attach or a recovery re-link reads what is bound, not what was picked). */
function LinkedAccount({ accountId, platform }: { accountId: string; platform: Platform }) {
  const meQ = useAccountAvatar(accountId);
  const me = meQ.data;
  const fansly = platform === "fansly";
  const proxiesQ = useProxyList(true);
  return (
    <div className="space-y-4">
      <LinkedLine />
      <AccountChip
        accountId={accountId} name={me?.name} username={me?.username} avatar={pickAvatarUrl(me)}
        sub={fansly && me?.username ? fanslyProfile(me.username) : undefined}
      />
      {fansly && meQ.isSuccess && !me && <p className="text-sm text-err">{FANSLY_T.accountInfoError}</p>}
      {platform === "onlyfans" && proxiesQ.isSuccess && proxiesQ.isFetchedAfterMount && (
        <p className={cn("text-sm", HB_DIM)}>{proxyText(currentProxy(proxiesQ.data, accountId), proxiesQ.data)}</p>
      )}
      {platform === "onlyfans" && proxiesQ.isError && <p className="text-sm text-err">Couldn&apos;t read this account&apos;s proxy.</p>}
    </div>
  );
}

/** A Fansly account's profile address, as Infloww's linked Fansly account reads. */
export const fanslyProfile = (username: string) => `fansly.com/${username}`;

export function AccountChip({ accountId, name, username, avatar, sub }: {
  accountId: string; name?: string | null; username?: string | null; avatar?: string | null;
  /** The line under the name in place of @username (a Fansly account's fansly.com/username). */
  sub?: string;
}) {
  return (
    <div className="flex items-center gap-3">
      {avatar
        ? <img src={avatar} alt="" className="h-10 w-10 rounded-full object-cover" />
        : <span aria-hidden className="grid h-10 w-10 place-items-center rounded-full bg-white/[.09] text-sm">{(name || accountId).slice(0, 1).toUpperCase()}</span>}
      <span className="min-w-0">
        <span className="block truncate text-sm font-medium">{name || accountId}</span>
        {(sub || username) && <span className={cn("block truncate text-xs", HB_DIM)}>{sub ?? `@${username}`}</span>}
      </span>
    </div>
  );
}

/** "Select your role": Admin/employee goes to the alternative method; Creator signs in. */
function SelectRole({ onAdmin, onCreator, onCancel }: { onAdmin: () => void; onCreator: () => void; onCancel: () => void }) {
  const [role, setRole] = useState<"admin" | "creator" | null>(null);
  return (
    <div className="space-y-4">
      <p className={STEP_TITLE}>{T.selectRoleTitle}</p>
      <div role="radiogroup" aria-label={T.selectRoleTitle} className={RADIO_GROUP}>
        {([["admin", "Admin/employee"], ["creator", "Creator (Owner of the OnlyFans account)"]] as const).map(([v, l]) => (
          <label key={v} className={RADIO_ITEM}>
            <input type="radio" name="role" checked={role === v} onChange={() => setRole(v)} className={RADIO} />
            {l}
          </label>
        ))}
      </div>
      <div className="flex justify-end gap-2">
        <FlowButton onClick={onCancel}>{T.cancel}</FlowButton>
        <FlowButton primary disabled={!role} onClick={role === "admin" ? onAdmin : onCreator}>{T.next}</FlowButton>
      </div>
    </div>
  );
}

/** "Linking OnlyFans account (Alternative method)", Infloww's four steps with our pages named. */
function AlternativeMethod() {
  const steps = [
    "Add the creator to your organization on Inflowwww as a user, restricting their permissions to add creators only. Note that the creator can view the information of other creators linked to your organization’s Inflowwww account when you do this.",
    "Have the creator activate their employee account via email, and log in to Inflowwww.",
    "Direct the creator to “Manage creators” and to click on “Link creator account” to complete the steps and verification of their OnlyFans account on their computer.",
    "Once the creator’s OnlyFans account is linked to Inflowwww, delete the creator’s Inflowwww user account.",
  ];
  return (
    <div className="space-y-4">
      <p className={STEP_TITLE}>{T.altMethodTitle}</p>
      <p role="alert" className="rounded-lg bg-[rgba(255,161,95,.12)] p-3 text-sm text-[#ffa15f]">
        Caution: This method exposes your organization’s data to external risk. This should be used as a last resort only
        if all other attempts to link the creator’s OnlyFans account have failed.
      </p>
      <ol className="space-y-3">
        {steps.map((s, i) => (
          <li key={i} className="text-sm">
            <span className="block font-medium">Step {i + 1}</span>
            <span className={HB_DIM}>{s}</span>
          </li>
        ))}
      </ol>
      <a href="/employees" target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-sm text-cta hover:underline">
        Employees <ExternalLink className="h-3.5 w-3.5" aria-hidden />
      </a>
    </div>
  );
}

/** The header's primary button (creators-manage#9): HB's primary at 36px, 16px weight 500 black on the orange action
 *  fill, 8px corners, its user-plus icon 8px before the text (#10, #11; 01-home.png). */
export function AddCreatorButton({ onClick }: { onClick: () => void }) {
  // `generous`'s 12px sides (#9): 136px wide, as 01-home.png's.
  return <HbButton size="lg" icon={UserPlus} onClick={onClick} className="px-3">Add creator</HbButton>;
}
