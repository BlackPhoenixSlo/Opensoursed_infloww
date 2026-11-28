"use client";


import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { AccountChip, LINKERS, profileLine, type SectionKey } from "@/components/setup/AddCreatorModal";
import { FANSLY_T } from "@/components/setup/FanslyPasteSessionCard";
import {
  CreatorsDetailsForm, EditCreatorForm, FlowButton, FlowModal, HB_DIM, STEP_TITLE, SelectProxyUI, T, applyProxy, assignedIds,
  creatorDetailsError, currentProxy, proxyChoiceReady, proxyText, toast, useProxyList, useRoster, useSaveAccountDetails,
  type AccountDetails, type ProxyChoice,
} from "@/components/setup/creatorFlow";
import { pickAvatarUrl, useAccountAvatar } from "@/hooks/useAccountAvatar";
import { useCreatorProfiles, type CreatorDetails, type DraftCreator } from "@/lib/creatorProfiles";
import { PLATFORM_NAME, accountPlatform, hasSession, platformRow } from "@/lib/platform";
import { type AccountMeta } from "@/lib/relay";
import { cn } from "@/lib/utils";

const NOT_WIRED = "not wired";
const BOX = "flex items-center justify-between gap-2 rounded-lg bg-[#161616] p-3 [html[data-theme=light]_&]:bg-black/5";

export function EditAccountModal({ account, conn, onClose, onLink }: {
  account: AccountMeta;
  conn: string;
  onClose: () => void;
  onLink?: (at: SectionKey, expectedAccountId?: string) => void;
}) {
  const profiles = useCreatorProfiles();
  const roster = useRoster();
  const save = useSaveAccountDetails(profiles);
  const profile = profiles.profiles[account.id] ?? {};
  const platform = accountPlatform(account);
  const row = platformRow(platform);
  const relink = row && (() => {
    onClose();
    if (LINKERS[row.relink].pinsAccount) onLink?.(row.relink, account.id);
    else onLink?.(row.relink);
  });
  const [creator, setCreator] = useState<CreatorDetails>({
    name: profile.name ?? account.nickname ?? account.name ?? "", gender: profile.gender ?? "", avatar: profile.avatar,
  });
  const [details, setDetails] = useState<AccountDetails | null>(null);
  const value: AccountDetails = details ?? {
    nickname: account.nickname ?? "", tag: profile.tag ?? "", employeeIds: assignedIds(roster, account.id), notes: profile.notes ?? "",
  };
  const [changing, setChanging] = useState(false);
  const me = useAccountAvatar(account.id).data;
  const proxiesQ = useProxyList();
  const bound = currentProxy(proxiesQ.data, account.id);
  const connected = conn === "Connected";
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
          <span className="text-sm">{PLATFORM_NAME[platform]}</span>
        </div>
        <div>
          <span className="mb-1 block text-sm font-medium">{T.linkedAccount}</span>
          <div className={BOX}>
            <AccountChip
              accountId={account.id} name={me?.name ?? account.name ?? account.nickname} username={me?.username} avatar={pickAvatarUrl(me)}
              sub={profileLine(row, me?.username)}
            />
            {connected ? (
              <FlowButton disabled title={NOT_WIRED}>{T.unlink}</FlowButton>
            ) : relink && (
              <FlowButton onClick={relink}>{T.linkAccount}</FlowButton>
            )}
          </div>
          {row && hasSession(row) && conn === "Disconnected" && <p className="mt-1 text-sm text-err">{FANSLY_T.rebind}</p>}
        </div>
        {row?.bindsProxy && (
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
                {!connected && relink && <FlowButton onClick={relink}>{T.linkAccount}</FlowButton>}
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
