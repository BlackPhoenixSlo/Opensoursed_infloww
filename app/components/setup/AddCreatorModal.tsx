"use client";


import { Globe, Puzzle, User, UserPlus } from "lucide-react";
import Link from "next/link";
import { Fragment, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import LinkedCreatorProxy from "./LinkedCreatorProxy";
import PasteCurlCard from "@/components/setup/PasteCurlCard";
import {
  buildAccountPayload, canBack, canClose, canNext, canPickPlatform, signInBusy, profileName, useWizardReducer, type Method,
  type BusySource, type WizardState,
} from "@/components/setup/addCreatorWizard";
import { PLATFORMS, PLATFORM_NAME, hasSession, platformRow, type Platform, type PlatformRow } from "@/lib/platform";
import BrowserbaseLoginCard from "@/components/setup/BrowserbaseLoginCard";
import FanslyPasteSessionCard, { FANSLY_T } from "@/components/setup/FanslyPasteSessionCard";
import {
  CreatorsDetailsForm, EditCreatorForm, HB_DIM, LinkedLine, T, creatorDetailsError,
  assignedIds, currentProxy, proxyText, toast, useProxyList, useRoster, useSaveAccountDetails,
} from "@/components/setup/creatorFlow";
import { attachDefaultProxy } from "@/components/setup/proxyApi";
import { PlatformLogo } from "@/components/shell/PlatformSwitcher";
import { HbButton, IfButton, IfModal } from "@/components/ui/infloww";
import { pickAvatarUrl, useAccountAvatar } from "@/hooks/useAccountAvatar";
import { useCreatorProfiles, type CreatorDetails, type DraftCreator } from "@/lib/creatorProfiles";
import { LOGINS_PAGE } from "@/lib/loginPaste";
import { proxyImage } from "@/lib/mediaUrl";
import { textAvatar } from "@/lib/ofMirrorAvatar";
import { cn } from "@/lib/utils";

export const DESKTOP_ONLY_LINE = "The extension and keys are desktop-only. On a phone, link a creator with Browser login.";
const MOBILE_PASTE_LINE = "The extension needs desktop Chrome. On a phone, use Browser login.";
const mobileSessionLine = (label: string) => `The ${label} paste session is desktop-only. On a phone, use Browser login.`;

const SECTIONS = {
  paste: { id: "add-creator-paste-curl", name: "Extension", platform: "onlyfans", method: "extension" },
  browserbase: { id: "add-creator-browserbase", name: "Browserbase login", platform: "onlyfans", method: "browser" },
  fansly: { id: "add-creator-fansly", name: "Fansly paste session", platform: "fansly", method: "extension" },
  fanslyBrowser: { id: "add-creator-fansly-browser", name: "Fansly browser login", platform: "fansly", method: "browser" },
} as const;
export type SectionKey = keyof typeof SECTIONS;

type Relink = PlatformRow["relink"];

export const LINKERS: Record<Relink, { pinsAccount: boolean; modalSubmit: boolean; recovery: boolean }> = {
  browserbase: { pinsAccount: false, modalSubmit: false, recovery: true },
  fansly: { pinsAccount: true, modalSubmit: true, recovery: false },
};

export const profileLine = (row: PlatformRow | undefined, username: string | null | undefined): string | undefined =>
  row?.profileHost && username ? `${row.profileHost}/${username}` : undefined;

function Section({ k, hidden, children }: { k: SectionKey; hidden?: boolean; children: ReactNode }) {
  const s = SECTIONS[k];
  return (
    <section id={s.id} aria-label={s.name} hidden={hidden} tabIndex={-1} className="focus:outline-none">
      {children}
    </section>
  );
}

export const ROW_LINK_TITLE = T.linkCreatorAccount;

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
  const { loginDefault } = platformRow(state.platform);
  return (
    <div role="radiogroup" aria-label="Login method" className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      {METHODS.map(({ method, title, sub, icon: Icon, tag }) => {
        const on = state.method === method;
        return (
          <label
            key={method}
            className={cn(
              "flex cursor-pointer flex-col gap-1.5 rounded-lg border p-4 transition-colors",
              "has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-accent/40",
              on ? "border-accent bg-accent/10" : "border-border hover:border-accent",
            )}
          >
            <input
              type="radio" name="login-method" value={method} checked={on} disabled={signInBusy(state)}
              onChange={() => onChange(method)} className="sr-only"
            />
            <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[16px] font-semibold text-fg">
              <Icon className={cn("h-5 w-5", on ? "text-accent" : "text-muted")} aria-hidden />
              <span className="whitespace-nowrap">{title}</span>
              {tag && method === loginDefault && <span className="rounded bg-accent/15 px-1.5 py-0.5 text-[12px] font-medium text-accent">{tag}</span>}
            </span>
            <span className="text-[13px] leading-[18px] text-muted">{sub}</span>
          </label>
        );
      })}
    </div>
  );
}

export default function AddCreatorModal({ extInstalled, onClose, at, draft, linkAnother, expectedAccountId }: {
  extInstalled: boolean | null;
  onClose: () => void;
  at?: SectionKey;
  draft?: DraftCreator;
  linkAnother?: { creator: CreatorDetails; linked: Platform[] };
  expectedAccountId?: string;
}) {
  const profiles = useCreatorProfiles();
  const roster = useRoster();
  const save = useSaveAccountDetails(profiles);
  const [state, dispatch] = useWizardReducer({
    recovery: at && SECTIONS[at].platform, method: at && SECTIONS[at].method, draft, linkAnother,
  });
  const { step, details, platform, method, recovery, fresh } = state;
  // dispatch says whether the wizard took the action: a save runs only on a taken submitStart, so a double-click saves once
  const row = platformRow(platform);
  const linker = LINKERS[row.relink];
  const linkedId = step.kind === "linked" ? step.accountId : null;
  const meQ = useAccountAvatar(linkedId);
  const ofName = profileName(meQ.data);
  const reportBusy = useMemo(() => {
    const to = (source: BusySource) => (value: boolean) => { dispatch({ type: "busy", source, value }); };
    return { login: to("login"), extension: to("extension"), paste: to("paste"), proxy: to("proxy") };
  }, [dispatch]);
  useEffect(() => {
    if (linkedId && ofName) dispatch({ type: "profile", accountId: linkedId, name: ofName });
  }, [linkedId, ofName, dispatch]);

  useEffect(() => {
    if (!at) return;
    const el = document.getElementById(SECTIONS[at].id);
    el?.scrollIntoView?.({ block: "start" });
    el?.focus();
  }, [at]);

  // Done waits for the link-time draft write so its whole-blob write is last; a late reply would put the old blob back
  const linkWrite = useRef<Promise<void> | null>(null);
  const linked = (platform: Platform) => (id: string) => {
    const took = dispatch({
      type: "linked", accountId: id, platform,
      account: { nickname: details.name, tag: profiles.profiles[id]?.tag ?? "", employeeIds: assignedIds(roster, id), notes: profiles.profiles[id]?.notes ?? "" },
    });
    if (took && state.draftId) {
      const write = profiles.profiles[id]
        ? profiles.removeDraft(state.draftId)
        : profiles.linkAccount(id, { name: details.name, gender: details.gender, avatar: details.avatar }, state.draftId);
      linkWrite.current = write.catch((e: Error) => toast(e.message, "err"));
    }
  };

  const title = fresh ? T.addCreator : ROW_LINK_TITLE;
  const nickname = recovery ? "" : details.name;
  const closable = canClose(state);
  const close = () => { if (closable) onClose(); };
  const cancel = <IfButton onClick={close} disabled={!closable}>{T.cancel}</IfButton>;

  // A Platform's sign-ins stay mounted (`hidden`, never conditionally rendered): unmounting BrowserbaseLoginCard cancels its running job.
  const loginCards: Record<Relink, (r: PlatformRow, on: boolean) => ReactNode> = {
    browserbase: (r, on) => (
      <>
        <Section k="browserbase" hidden={!on || method !== "browser"}>
          <BrowserbaseLoginCard
            platform={r.key} onLinked={linked(r.key)} initialNickname={nickname} keepProxy={recovery} active={on && method === "browser"}
            onBusy={reportBusy.login} expectedAccountId={expectedAccountId}
          />
          {!recovery && (
            <Link href={LOGINS_PAGE} className="mt-3 inline-block text-sm text-accent hover:text-accent-hover">
              Several creators? Paste all their logins at once
            </Link>
          )}
        </Section>
        <Section k="paste" hidden={!on || method !== "extension"}>
          <div className="hidden md:block">
            <PasteCurlCard
              extInstalled={extInstalled} onLinked={linked(r.key)} initialNickname={nickname} formId={r.extensionFormId}
              attach={recovery ? undefined : attachDefaultProxy} active={on && method === "extension"} onBusy={reportBusy.extension}
            />
          </div>
          <p className="md:hidden text-sm text-muted">{MOBILE_PASTE_LINE}</p>
        </Section>
      </>
    ),
    fansly: (r, on) => (
      <>
        <Section k="fanslyBrowser" hidden={!on || method !== "browser"}>
          <BrowserbaseLoginCard
            platform={r.key} onLinked={linked(r.key)} initialNickname={nickname} keepProxy={recovery}
            active={on && method === "browser"} onBusy={reportBusy.login} expectedAccountId={expectedAccountId}
          />
        </Section>
        {on && (
          <Section k="fansly" hidden={method !== "extension"}>
            <p className="md:hidden text-sm text-muted">{mobileSessionLine(r.label)}</p>
            <div className="hidden md:block">
              <FanslyPasteSessionCard
                onLinked={linked(r.key)} initialNickname={nickname} formId={r.extensionFormId} expectedAccountId={expectedAccountId}
                onBusy={reportBusy.paste}
              />
            </div>
          </Section>
        )}
      </>
    ),
  };

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
            {PLATFORMS.map(({ key: value, label }) => (
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
                <span className="text-base font-medium">{label}</span>
              </label>
            ))}
          </div>
          {hasSession(row) && <p className="md:hidden text-sm text-muted">{mobileSessionLine(row.label)}</p>}
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
          {fresh && (
            <p className={cn("text-sm", HB_DIM)}>{T.stepOf(3, 3)} · {T.linkPlatformAccount(PLATFORM_NAME[platform])}</p>
          )}
          <MethodChoice state={state} onChange={(value) => dispatch({ type: "setField", field: "method", value })} />
          {PLATFORMS.map((r) => <Fragment key={r.key}>{loginCards[r.relink](r, r.key === platform)}</Fragment>)}
          {PLATFORMS.filter(({ key }) => key !== platform && canPickPlatform(state, key)).map(({ key, label }) => (
            <button
              key={key} type="button" onClick={() => dispatch({ type: "setField", field: "platform", value: key })}
              className="inline-flex items-center gap-1.5 text-[13px] text-accent hover:text-accent-hover"
            >
              <PlatformLogo platform={key} className="h-3.5 w-3.5" />
              {`Link ${/^[aeiou]/i.test(label) ? "an" : "a"} ${label} account instead`}
            </button>
          ))}
        </div>
      );
      footer = (
        <>
          {cancel}
          {canBack(state) && <IfButton onClick={() => dispatch({ type: "back" })}>{T.back}</IfButton>}
          {linker.modalSubmit && method === "extension" && (
            <IfButton variant="primary" type="submit" form={row.extensionFormId} className="max-md:hidden">{T.done}</IfButton>
          )}
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
          {row.bindsProxy && <LinkedCreatorProxy key={step.accountId} accountId={step.accountId} onBusy={reportBusy.proxy} />}
        </div>
      );
      footer = recovery ? <IfButton variant="primary" disabled={state.busy.proxy} onClick={onClose}>{T.done}</IfButton> : (
        <IfButton
          variant="primary" disabled={!canNext(state)}
          onClick={() => {
            if (!dispatch({ type: "submitStart" })) return;
            const payload = buildAccountPayload(state, step, roster, ofName);
            void (linkWrite.current ?? Promise.resolve()).then(() => save.mutate(payload, {
              onSuccess: () => { toast(fresh ? "Creator added" : T.updateSuccess); dispatch({ type: "submitOk" }); onClose(); },
              onError: (e) => { toast((e as Error).message, "err"); dispatch({ type: "submitErr" }); },
            }));
          }}
        >
          {step.busy ? "Saving…" : T.done}
        </IfButton>
      );
      break;
    case "success":
      return null;
  }

  return (
    <IfModal title={title} width={600} onClose={close} closable={closable} footer={footer} footerSlot={step.kind === "login" && (!linker.modalSubmit || method === "browser")}>
      {body}
    </IfModal>
  );
}

function LinkedAccount({ accountId, platform }: { accountId: string; platform: Platform }) {
  const meQ = useAccountAvatar(accountId);
  const me = meQ.data;
  const row = platformRow(platform);
  const proxiesQ = useProxyList(true);
  return (
    <div className="space-y-4">
      <LinkedLine />
      <AccountChip
        accountId={accountId} name={me?.name} username={me?.username} avatar={row.bindsProxy ? proxyImage(pickAvatarUrl(me), accountId) : pickAvatarUrl(me)}
        sub={profileLine(row, me?.username)}
      />
      {hasSession(row) && meQ.isSuccess && !me && <p className="text-sm text-err">{FANSLY_T.accountInfoError}</p>}
      {row.bindsProxy && proxiesQ.isSuccess && proxiesQ.isFetchedAfterMount && (
        <p className={cn("text-sm", HB_DIM)}>{proxyText(currentProxy(proxiesQ.data, accountId), proxiesQ.data)}</p>
      )}
      {row.bindsProxy && proxiesQ.isError && <p className="text-sm text-err">Couldn&apos;t read this account&apos;s proxy.</p>}
    </div>
  );
}

export function AccountChip({ accountId, name, username, avatar, sub }: {
  accountId: string; name?: string | null; username?: string | null; avatar?: string | null;
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

export function AddCreatorButton({ onClick }: { onClick: () => void }) {
  return <HbButton size="lg" icon={UserPlus} onClick={onClick} className="px-3">Add creator</HbButton>;
}
