"use client";

/**
 * AddCreatorModal — Add creator / Link creator account: the main Add creator route restores Infloww's Creator details
 * and platform steps before the sign-in; existing drafts and relink actions keep their direct sign-in entry:
 *
 *   details and platform   the new Creator's image, name and gender, followed by the platform choice.
 *   login   the two ways in as two big choices at the top (a radiogroup, "Login method"):
 *             Browser login  (first, Recommended): BrowserbaseLoginCard, a remote browser on Browserbase's network;
 *                            email + password, any check solved in the live view, a 2FA code typed on the card.
 *             Extension      (the fallback, "if browser login doesn't work"): PasteCurlCard, the Chrome extension's
 *                            Copy cURL pasted here. Desktop only: on a phone the panel says so.
 *           Under them, small, "Link a Fansly account" swaps to the Fansly paste session (the extension's session
 *           copy, so Browser login is off there). The proxy is the relay's automatic one (its pool's tier-aware pick
 *           for a new login; a row's re-link keeps the account's).
 *           Both OnlyFans sign-ins stay mounted (the other one hidden), so a Browser login still running links even
 *           while the Extension panel is open; the shown one's primary button sits in the footer after Cancel.
 *   linked  "Creator account is linked": the account (its OF photo, name, @username and id, from its own /users/me),
 *           the proxy the relay has it on (read back from GET /admin/proxies), and below it the account details
 *           (Nickname, prefilled with the OF name once that read lands; Tag, Assigned employees, Internal notes);
 *           Done saves them (a blank nickname takes the account's own name) and closes. A row's recovery shows the
 *           account only, and Done closes.
 *
 * Kept out of the way, not dropped: a custom proxy (Creators › Custom proxy, a row's Change proxy), Make default (a
 * row's menu), the extension's static_param override (folded under Troubleshooting). Creators are no longer saved
 * before a login; drafts saved earlier still open here from their row.
 *
 * Entry points: the header's Add creator; a draft's "Link creator account" (`draft`) and a row's "Link another
 * account" (`linkAnother`, its platforms taken: Fansly when OnlyFans is); a row's recovery actions and the 2FA
 * notification's `?relink=browserbase` (`at`, the sign-in that performs it, focused).
 */

import { Globe, Puzzle, User, UserPlus } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import PasteCurlCard from "@/components/setup/PasteCurlCard";
import {
  buildAccountPayload, canNext, canPickPlatform, profileName, useWizardReducer, type Method, type Platform, type WizardState,
} from "@/components/setup/addCreatorWizard";
import BrowserbaseLoginCard from "@/components/setup/BrowserbaseLoginCard";
import FanslyPasteSessionCard, { FANSLY_FORM_ID, FANSLY_T } from "@/components/setup/FanslyPasteSessionCard";
import {
  CreatorsDetailsForm, EditCreatorForm, HB_DIM, LinkedLine, T, creatorDetailsError,
  assignedIds, bindPoolProxy, currentProxy, proxyText, toast, useProxyList,
  useRoster, useSaveAccountDetails,
} from "@/components/setup/creatorFlow";
import { PlatformLogo } from "@/components/shell/PlatformSwitcher";
import { HbButton, IfButton, IfModal } from "@/components/ui/infloww";
import { pickAvatarUrl, useAccountAvatar } from "@/hooks/useAccountAvatar";
import { useCreatorProfiles, type CreatorDetails, type DraftCreator } from "@/lib/creatorProfiles";
import { proxyImage } from "@/lib/mediaUrl";
import { textAvatar } from "@/lib/ofMirrorAvatar";
import { cn } from "@/lib/utils";

/** The page's one line for phones (spec, Mobile). */
export const DESKTOP_ONLY_LINE = "The extension and keys are desktop-only. On a phone, link a creator with Browser login.";
/** The Extension panel's line for phones. */
export const MOBILE_PASTE_LINE = "The extension needs desktop Chrome. On a phone, use Browser login.";
/** The Fansly sign-in's line for phones. */
export const MOBILE_FANSLY_LINE = "The Fansly paste session is desktop-only.";

/** Our sign-in sections (the region names a row's recovery and the 2FA notification focus). */
const SECTIONS = {
  paste: { id: "add-creator-paste-curl", name: "Extension", platform: "onlyfans", method: "extension" },
  browserbase: { id: "add-creator-browserbase", name: "Browserbase login", platform: "onlyfans", method: "browser" },
  fansly: { id: "add-creator-fansly", name: "Fansly paste session", platform: "fansly", method: "extension" },
} as const;
export type SectionKey = keyof typeof SECTIONS;

export const PLATFORM_LABEL: Record<Platform, string> = { onlyfans: "OnlyFans", fansly: "Fansly" };

function Section({ k, hidden, children }: { k: SectionKey; hidden?: boolean; children: ReactNode }) {
  const s = SECTIONS[k];
  return (
    <section id={s.id} aria-label={s.name} hidden={hidden} tabIndex={-1} className="focus:outline-none">
      {children}
    </section>
  );
}

/** A row's entry points, and a draft's, read `creators0174`. */
export const ROW_LINK_TITLE = T.linkCreatorAccount;

/** The two ways in, the two big choices at the top. */
const METHODS: { method: Method; title: string; sub: string; icon: typeof Globe; tag?: string }[] = [
  {
    method: "browser", title: "Browser login", icon: Globe, tag: "Recommended",
    sub: "Sign in with the creator's email and password. No extension, works on a phone too.",
  },
  {
    method: "extension", title: "Extension", icon: Puzzle,
    sub: "If browser login doesn't work. Sign in on your own Chrome and paste the copy.",
  },
];

function MethodChoice({ state, onChange }: { state: WizardState; onChange: (m: Method) => void }) {
  const fansly = state.platform === "fansly";
  return (
    <div role="radiogroup" aria-label="Login method" className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      {METHODS.map(({ method, title, sub, icon: Icon, tag }) => {
        const off = fansly && method === "browser";
        const on = state.method === method;
        return (
          <label
            key={method} title={off ? "Browser login is for OnlyFans accounts" : undefined}
            className={cn(
              "flex cursor-pointer flex-col gap-1.5 rounded-lg border p-4 transition-colors",
              "has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-accent/40",
              on ? "border-accent bg-accent/10" : "border-border hover:border-accent",
              off && "cursor-not-allowed opacity-40 hover:border-border",
            )}
          >
            <input
              type="radio" name="login-method" value={method} checked={on} disabled={off}
              onChange={() => onChange(method)} className="sr-only"
            />
            <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[16px] font-semibold text-fg">
              <Icon className={cn("h-5 w-5", on ? "text-accent" : "text-muted")} aria-hidden />
              <span className="whitespace-nowrap">{title}</span>
              {tag && !fansly && <span className="rounded bg-accent/15 px-1.5 py-0.5 text-[12px] font-medium text-accent">{tag}</span>}
            </span>
            <span className="text-[13px] leading-[18px] text-muted">{sub}</span>
          </label>
        );
      })}
    </div>
  );
}

export default function AddCreatorModal({ extInstalled, onClose, at, draft, linkAnother }: {
  extInstalled: boolean | null;
  onClose: () => void;
  /** A row's recovery action: straight to the sign-in that performs it. */
  at?: SectionKey;
  /** A Creator saved before (a draft), not linked yet: its details ride along. */
  draft?: DraftCreator;
  /** "Link another account": the Creator's details and the platforms it has an account on. */
  linkAnother?: { creator: CreatorDetails; linked: Platform[] };
}) {
  const profiles = useCreatorProfiles();
  const roster = useRoster();
  const save = useSaveAccountDetails(profiles);
  // `dispatch` answers whether the wizard took the action: a save runs only when its submitStart was taken, so a
  // double-click's second click saves nothing (useWizardReducer).
  const [state, dispatch] = useWizardReducer({
    recovery: at && SECTIONS[at].platform, method: at && SECTIONS[at].method, draft, linkAnother,
  });
  const { step, details, platform, method, recovery } = state;
  // The automatic proxy: a new account goes on the relay's pool when it has one (Browser login: the relay picks the
  // same itself). A row's re-link binds nothing, so the account keeps the proxy it is on.
  const proxiesQ = useProxyList();
  const autoPool = !recovery && !!proxiesQ.data?.pool?.size;
  const of = platform === "onlyfans";
  const linkedId = step.kind === "linked" ? step.accountId : null;
  const meQ = useAccountAvatar(linkedId);
  const ofName = profileName(meQ.data);
  // The OF profile read prefills a blank nickname (the reducer keeps a typed one).
  useEffect(() => {
    if (linkedId && ofName) dispatch({ type: "profile", accountId: linkedId, name: ofName });
  }, [linkedId, ofName, dispatch]);

  useEffect(() => {
    if (!at) return;
    const el = document.getElementById(SECTIONS[at].id);
    el?.scrollIntoView?.({ block: "start" });
    el?.focus();
  }, [at]);

  const linked = (platform: Platform) => (id: string) => dispatch({
    type: "linked", accountId: id, platform,
    account: { nickname: details.name, tag: profiles.profiles[id]?.tag ?? "", employeeIds: assignedIds(roster, id), notes: profiles.profiles[id]?.notes ?? "" },
  });

  const title = at || draft || linkAnother ? ROW_LINK_TITLE : T.addCreator;
  const nickname = recovery ? "" : details.name;
  const other: Platform = of ? "fansly" : "onlyfans";
  const cancel = <IfButton onClick={onClose}>{T.cancel}</IfButton>;

  let body: ReactNode;
  let footer: ReactNode;
  switch (step.kind) {
    case "details":
      body = (
        <div className="space-y-4">
          <p className={cn("text-sm", HB_DIM)}>{T.stepOf(1, 3)} · {T.creatorDetails}</p>
          <CreatorsDetailsForm value={details} onChange={(value) => dispatch({ type: "setDetails", value })} />
        </div>
      );
      footer = (
        <>
          {cancel}
          <IfButton variant="primary" disabled={!!creatorDetailsError(details)} onClick={() => dispatch({ type: "detailsNext" })}>
            {T.next}
          </IfButton>
        </>
      );
      break;
    case "platform":
      body = (
        <div className="space-y-4">
          <p className={cn("text-sm", HB_DIM)}>{T.stepOf(2, 3)}</p>
          <p className="text-sm font-medium text-fg">{T.whichPlatform}</p>
          <div role="radiogroup" aria-label={T.platform} className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {(["onlyfans", "fansly"] as const).map((value) => (
              <label key={value} className={cn(
                "flex cursor-pointer items-center gap-3 rounded-lg border p-4 transition-colors",
                platform === value ? "border-accent bg-accent/10" : "border-border hover:border-accent",
                state.taken.includes(value) && "cursor-not-allowed opacity-40",
              )}>
                <input
                  type="radio" name="creator-platform" value={value} checked={platform === value}
                  disabled={state.taken.includes(value)}
                  onChange={() => dispatch({ type: "setField", field: "platform", value })} className="sr-only"
                />
                <PlatformLogo platform={value} className="h-5 w-5" />
                <span className="text-base font-medium">{PLATFORM_LABEL[value]}</span>
              </label>
            ))}
          </div>
        </div>
      );
      footer = (
        <>
          {cancel}
          <IfButton onClick={() => dispatch({ type: "back" })}>{T.back}</IfButton>
          <IfButton variant="primary" onClick={() => dispatch({ type: "platformNext" })}>{T.next}</IfButton>
        </>
      );
      break;
    case "login":
      body = (
        <div className="space-y-6">
          {!recovery && !state.draftId && !state.taken.length && (
            <p className={cn("text-sm", HB_DIM)}>{T.stepOf(3, 3)} · {T.linkPlatformAccount(PLATFORM_LABEL[platform])}</p>
          )}
          <MethodChoice state={state} onChange={(value) => dispatch({ type: "setField", field: "method", value })} />
          <Section k="browserbase" hidden={!of || method !== "browser"}>
            <BrowserbaseLoginCard onLinked={linked("onlyfans")} initialNickname={nickname} keepProxy={recovery} active={of && method === "browser"} />
          </Section>
          <Section k="paste" hidden={!of || method !== "extension"}>
            {/* No extension on a phone. */}
            <div className="hidden md:block">
              <PasteCurlCard
                extInstalled={extInstalled} onLinked={linked("onlyfans")} initialNickname={nickname}
                attach={autoPool ? bindPoolProxy : undefined} active={of && method === "extension"}
              />
            </div>
            <p className="md:hidden text-sm text-muted">{MOBILE_PASTE_LINE}</p>
          </Section>
          {!of && (
            <Section k="fansly">
              <p className="md:hidden text-sm text-muted">{MOBILE_FANSLY_LINE}</p>
              <div className="hidden md:block">
                <FanslyPasteSessionCard onLinked={linked("fansly")} initialNickname={nickname} formId={FANSLY_FORM_ID} />
              </div>
            </Section>
          )}
          {canPickPlatform(state, other) && (
            <button
              type="button" onClick={() => dispatch({ type: "setField", field: "platform", value: other })}
              className="inline-flex items-center gap-1.5 text-[13px] text-accent hover:text-accent-hover"
            >
              <PlatformLogo platform={other} className="h-3.5 w-3.5" />
              {of ? "Link a Fansly account instead" : "Link an OnlyFans account instead"}
            </button>
          )}
        </div>
      );
      // Infloww's Fansly sign-in: Done beside Cancel submits the session (`creators0108`, @12411710). OnlyFans: the
      // shown sign-in puts its own button after Cancel (footerSlot).
      footer = (
        <>
          {cancel}
          {!recovery && !state.draftId && !state.taken.length && <IfButton onClick={() => dispatch({ type: "back" })}>{T.back}</IfButton>}
          {!of && <IfButton variant="primary" type="submit" form={FANSLY_FORM_ID}>{T.done}</IfButton>}
        </>
      );
      break;
    case "linked":
      body = (
        <div className="space-y-6">
          <LinkedAccount accountId={step.accountId} platform={platform} />
          {!recovery && (
            <div>
              <p className="mb-4 text-[14px] font-semibold text-fg">{T.accountDetails}</p>
              <EditCreatorForm
                value={step.account} onChange={(value) => dispatch({ type: "setField", field: "account", value })}
                tags={profiles.tags} roster={roster}
              />
            </div>
          )}
        </div>
      );
      footer = recovery ? <IfButton variant="primary" onClick={onClose}>{T.done}</IfButton> : (
        <IfButton
          variant="primary" disabled={!canNext(state)}
          onClick={() => {
            if (!dispatch({ type: "submitStart" })) return;
            save.mutate(buildAccountPayload(state, step, roster, ofName), {
              onSuccess: () => { toast(at || draft || linkAnother ? T.updateSuccess : "Creator added"); dispatch({ type: "submitOk" }); onClose(); },
              onError: (e) => { toast((e as Error).message, "err"); dispatch({ type: "submitErr" }); },
            });
          }}
        >
          {step.busy ? "Saving…" : T.done}
        </IfButton>
      );
      break;
    case "success":
      body = <LinkedLine />;
      footer = <IfButton variant="primary" onClick={onClose}>{T.done}</IfButton>;
      break;
  }

  return (
    // `maskClosable:false` (creators-manage#54): the mask does not close it; Escape and the × do.
    <IfModal title={title} width={600} onClose={onClose} footer={footer} footerSlot={step.kind === "login" && of}>
      {body}
    </IfModal>
  );
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
        accountId={accountId} name={me?.name} username={me?.username} avatar={fansly ? pickAvatarUrl(me) : proxyImage(pickAvatarUrl(me), accountId)}
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

/** The linked account: its photo (else the name's initials, else a profile icon), its name (else its id), and under it
 *  @username (or `sub`) and the OF user id. */
export function AccountChip({ accountId, name, username, avatar, sub }: {
  accountId: string; name?: string | null; username?: string | null; avatar?: string | null;
  /** The line under the name in place of @username (a Fansly account's fansly.com/username). */
  sub?: string;
}) {
  const [broken, setBroken] = useState(false);
  const letters = textAvatar((name || username || "").trim());
  const handle = sub ?? (username ? `@${username}` : null);
  const named = !!(name || username);
  return (
    <div className="flex items-center gap-3">
      {avatar && !broken
        ? <img src={avatar} alt="" onError={() => setBroken(true)} className="h-10 w-10 shrink-0 rounded-full object-cover" />
        : (
          <span aria-hidden className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-white/[.09] text-sm font-medium">
            {letters || <User className="h-5 w-5 text-muted" />}
          </span>
        )}
      <span className="min-w-0">
        <span className="block truncate text-sm font-medium">{name || username || accountId}</span>
        {(handle || named) && (
          <span className={cn("block truncate text-xs", HB_DIM)}>
            {handle && <span>{handle}</span>}
            {handle && named && " · "}
            {named && <span>ID {accountId}</span>}
          </span>
        )}
      </span>
    </div>
  );
}

/** The header's primary button (creators-manage#9): HB's primary at 36px, 16px weight 500 black on the orange action
 *  fill, 8px corners, its user-plus icon 8px before the text (#10, #11; 01-home.png). */
export function AddCreatorButton({ onClick }: { onClick: () => void }) {
  // `generous`'s 12px sides (#9): 136px wide, as 01-home.png's.
  return <HbButton size="lg" icon={UserPlus} onClick={onClick} className="px-3">Add creator</HbButton>;
}
