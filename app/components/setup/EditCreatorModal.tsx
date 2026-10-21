"use client";

/**
 * Infloww's two edit modals (index.9f50f370.js, `UpdateCreator` and `EditCreators`), with Infloww's English
 * (creatorFlow.tsx's `T`):
 *
 *   EditAccountModal  "Edit account details", an account row's pencil or its ⋮ Edit: the Creator details, then
 *                     Account details: Platform, Linked account (Unlink when Connected, else Link account), Proxy
 *                     connection (OnlyFans: its status and proxy, Change, Delete), the account details form; Save.
 *   EditDraftModal    "Edit creator details", a Creator row with no account: the Creator details; Save.
 *
 * Wired: Change proxy (unbind, bind, reload session), the nickname, Assigned employees (Creator access), and the
 * Creator details, Tag and Internal notes (the `creators` profile). Not wired: Unlink and Delete connection (the Relay
 * cannot drop a session and keep its account; Delete on the row removes both).
 */

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { AccountChip, PLATFORM_LABEL, fanslyProfile, type SectionKey } from "@/components/setup/AddCreatorModal";
import { FANSLY_T } from "@/components/setup/FanslyPasteSessionCard";
import {
  CreatorsDetailsForm, EditCreatorForm, FlowButton, FlowModal, HB_DIM, STEP_TITLE, SelectProxyUI, T, applyProxy, assignedIds,
  creatorDetailsError, currentProxy, proxyChoiceReady, proxyText, toast, useProxyList, useRoster, useSaveAccountDetails,
  type AccountDetails, type ProxyChoice,
} from "@/components/setup/creatorFlow";
import { pickAvatarUrl, useAccountAvatar } from "@/hooks/useAccountAvatar";
import { useCreatorProfiles, type CreatorDetails, type DraftCreator } from "@/lib/creatorProfiles";
import { type AccountMeta } from "@/lib/relay";
import { cn } from "@/lib/utils";

const NOT_WIRED = "not wired";
/** A linked-account / proxy box: HB's #161616 fill, 8px corners, no border. */
const BOX = "flex items-center justify-between gap-2 rounded-lg bg-[#161616] p-3 [html[data-theme=light]_&]:bg-black/5";

export function EditAccountModal({ account, conn, onClose, onLink }: {
  account: AccountMeta;
  /** The row's connectivity label (creators-manage#40). */
  conn: string;
  onClose: () => void;
  /** Link account: the Add creator modal at the sign-in that relinks this platform. */
  onLink?: (at: SectionKey) => void;
}) {
  const profiles = useCreatorProfiles();
  const roster = useRoster();
  const save = useSaveAccountDetails(profiles);
  const profile = profiles.profiles[account.id] ?? {};
  const platform = account.platform ?? "onlyfans";
  const of = platform === "onlyfans";
  const [creator, setCreator] = useState<CreatorDetails>({
    name: profile.name ?? account.nickname ?? account.name ?? "", gender: profile.gender ?? "", avatar: profile.avatar,
  });
  const [details, setDetails] = useState<AccountDetails | null>(null);
  const value: AccountDetails = details ?? {
    nickname: account.nickname ?? "", tag: profile.tag ?? "", employeeIds: assignedIds(roster, account.id), notes: profile.notes ?? "",
  };
  const [changing, setChanging] = useState(false);
  // Fansly reads through the relay's Fansly shim, the same /users/me.
  const me = useAccountAvatar(account.id).data;
  const proxiesQ = useProxyList();
  const bound = currentProxy(proxiesQ.data, account.id);
  const connected = conn === "Connected";
  // A creator without a name is the only thing the profile's form refuses; an empty gender is an older account.
  const err = creatorDetailsError({ ...creator, gender: creator.gender || "Female" });

  return (
    <FlowModal
      title={T.editAccountDetails}
      onClose={onClose}
      footer={
        <>
          <FlowButton onClick={onClose}>{T.cancel}</FlowButton>
          <FlowButton
            primary disabled={!!err || !value.nickname.trim() || save.isPending}
            onClick={() => save.mutate(
              { accountId: account.id, before: account.nickname ?? "", roster, details: value, creator },
              {
                onSuccess: () => { toast(T.updateSuccess); onClose(); },
                onError: (e) => toast((e as Error).message, "err"),
              },
            )}
          >
            {T.save}
          </FlowButton>
        </>
      }
    >
      <div className="space-y-6">
        <CreatorsDetailsForm value={creator} onChange={setCreator} showTitle />
        <hr className="border-white/[.09] [html[data-theme=light]_&]:border-black/[.09]" />
        <p className={cn(STEP_TITLE, "mb-0")}>{T.accountDetails}</p>
        <div>
          <span className="mb-1 block text-sm font-medium">{T.platform}</span>
          <span className="text-sm">{PLATFORM_LABEL[platform]}</span>
        </div>
        <div>
          <span className="mb-1 block text-sm font-medium">{T.linkedAccount}</span>
          <div className={BOX}>
            <AccountChip
              accountId={account.id} name={me?.name ?? account.name ?? account.nickname} username={me?.username} avatar={pickAvatarUrl(me)}
              sub={!of && me?.username ? fanslyProfile(me.username) : undefined}
            />
            {connected ? (
              <FlowButton disabled title={NOT_WIRED}>{T.unlink}</FlowButton>
            ) : (
              <FlowButton onClick={() => { onClose(); onLink?.(of ? "paste" : "fansly"); }}>{T.linkAccount}</FlowButton>
            )}
          </div>
          {!of && conn === "Disconnected" && <p className="mt-1 text-sm text-err">{FANSLY_T.rebind}</p>}
        </div>
        {of && (
          <div>
            <span className="mb-1 block text-sm font-medium">{T.proxyConnection}</span>
            <div className={BOX}>
              <span className="min-w-0 space-y-1">
                <span className="flex items-center gap-2 text-sm">
                  {T.connection}
                  <span className={cn("rounded px-1.5 text-xs", connected ? "bg-ok/15 text-ok" : cn("bg-white/[.09]", HB_DIM))}>{conn}</span>
                </span>
                <span className={cn("block truncate text-xs", HB_DIM)}>{proxyText(bound, proxiesQ.data)}</span>
              </span>
              <span className="flex shrink-0 gap-2">
                {!connected && <FlowButton onClick={() => { onClose(); onLink?.("paste"); }}>{T.linkAccount}</FlowButton>}
                {/* Until the proxies read answers, `bound` is a guess ("No proxy") that Save would act on. */}
                <FlowButton disabled={!proxiesQ.isSuccess} onClick={() => setChanging(true)}>{T.change}</FlowButton>
                <FlowButton disabled title={NOT_WIRED}>{T.del}</FlowButton>
              </span>
            </div>
          </div>
        )}
        <EditCreatorForm value={value} onChange={setDetails} tags={profiles.tags} roster={roster} />
      </div>
      {changing && <ChangeProxyModal accountId={account.id} current={bound} onClose={() => setChanging(false)} />}
    </FlowModal>
  );
}

/** "Change proxy" (creators0054): the Proxy selection, then the account's proxy is switched and its session reloaded. */
function ChangeProxyModal({ accountId, current, onClose }: { accountId: string; current: ProxyChoice; onClose: () => void }) {
  const qc = useQueryClient();
  const [choice, setChoice] = useState<ProxyChoice>(current);
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    try {
      await applyProxy(accountId, current, choice);
      void qc.invalidateQueries({ queryKey: ["proxies"] });
      toast(T.switchProxySuccess);
      onClose();
    } catch (e) {
      toast((e as Error).message, "err");
    } finally {
      setBusy(false);
    }
  };
  return (
    <FlowModal
      title={T.changeProxy}
      onClose={onClose}
      footer={
        <>
          <FlowButton onClick={onClose}>{T.cancel}</FlowButton>
          <FlowButton primary disabled={!proxyChoiceReady(choice) || busy} onClick={() => void submit()}>{T.save}</FlowButton>
        </>
      }
    >
      <SelectProxyUI value={choice} onChange={setChoice} />
    </FlowModal>
  );
}

export function EditDraftModal({ draft, onClose }: { draft: DraftCreator; onClose: () => void }) {
  const profiles = useCreatorProfiles();
  const [creator, setCreator] = useState<CreatorDetails>({ name: draft.name, gender: draft.gender, avatar: draft.avatar });
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    try {
      await profiles.updateDraft(draft.id, creator);
      toast(T.updateSuccess);
      onClose();
    } catch (e) {
      toast((e as Error).message, "err");
    } finally {
      setBusy(false);
    }
  };
  return (
    <FlowModal
      title={T.editCreatorDetails}
      onClose={onClose}
      footer={
        <>
          <FlowButton onClick={onClose}>{T.cancel}</FlowButton>
          <FlowButton primary disabled={!!creatorDetailsError(creator) || busy || !profiles.wired} onClick={() => void submit()}>{T.save}</FlowButton>
        </>
      }
    >
      <CreatorsDetailsForm value={creator} onChange={setCreator} />
    </FlowModal>
  );
}
