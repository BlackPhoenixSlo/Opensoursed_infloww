"use client";

/**
 * S4S settings (Inventory §3.6; docs/spec/phase-03-share-for-share.md, UI), Infloww's `S4sSettingPage` (menu 55,
 * page-parity 15), for the creator picked on the rail: "Primary post" (its caption in the bordered box with the
 * "Primary" tag, or "Create post"; "Manage posts" opens the post list, up to 20, Create / Edit in a pop-up),
 * "Limit daily S4S" (1, 2 or 3 with its own Save, sending `daily_limit` only), "Discoverability settings" (saves on
 * toggle). Ours, labelled: "Take part in Share for Share" (the opt-in ADR-0011's bounded directory needs; Infloww has
 * none, a primary post is taking part), and "Profile shown to partners" (read only: the Creator's own OnlyFans name,
 * @username and avatar, which the Relay re-reads on every list). The post pop-up's "Add from Vault", and each post's
 * in Manage posts, pick up to 5 of the Creator's own vault items; Save stores them as vault references, and a
 * partner's slot reads them from this Creator's vault and uploads them to the partner's account (ADR-0015). A creator with posts always
 * has a Primary post (the Relay keeps it so), so "Create post" shows only for a creator with none.
 */

import { useState } from "react";
import { useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { ChevronLeft } from "lucide-react";

import { VaultPicker } from "@/components/chat/VaultPicker";
import { Field, FieldTextarea } from "@/components/settings/SettingsPanel";
import { EmptyState, IF_TABLE, IfButton, IfModal, IfSelect, IfSwitch, type IfOption } from "@/components/ui/infloww";
import { ExtraTag } from "@/components/ui/primitives";
import { ProjectionAvatar, S4SMediaStrip, message } from "@/components/s4s/s4sBits";
import { vaultTileThumb } from "@/hooks/useVaultCache";
import {
  S4S_DAILY_LIMITS, S4S_MAX_CAPTION, S4S_MAX_MEDIA, S4S_MAX_POSTS, S4S_PROFILES_KEY,
  createS4SPost, deleteS4SPost, editS4SPost, putS4SPostMedia, setPrimaryS4SPost, updateS4SProfile,
  type S4SPost, type S4SProfile, type S4SProfileUpdate, type S4SProfiles,
} from "@/lib/s4s";
import type { VaultMedia } from "@/lib/relay";
import { cn } from "@/lib/utils";

export const OPT_IN_LINE = "Off by default. Only agencies on this Inflowwww deployment can see a Creator you opt in.";
const LIMIT_OPTIONS: IfOption[] = S4S_DAILY_LIMITS.map((n) => ({
  value: String(n), label: `${n} Share for Share${n === 1 ? "" : "s"}`,
}));
const HEAD = "text-[16px] font-semibold text-fg";
const BOX = "rounded-lg border border-border";
const ROW = cn(BOX, "flex min-h-14 items-center justify-between gap-4 px-4 py-2 text-[14px] text-fg-dim");
const OUTLINE = "border-accent text-accent";
export const PARTNER_PROFILE_LINE = "From this creator's OnlyFans profile, read again each time this page opens.";
const tooMany = (n: number) => `An S4S post carries at most ${S4S_MAX_MEDIA} media; you picked ${n}.`;

/** One profile save; the reply replaces the cached profile, then the list reads again. */
function useSaveProfile(accountId: string) {
  const qc = useQueryClient();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  async function save(key: string, body: S4SProfileUpdate) {
    setBusy(key);
    setError(null);
    try {
      const saved = await updateS4SProfile(accountId, body);
      qc.setQueryData<S4SProfiles>(S4S_PROFILES_KEY, (d) => d && {
        ...d, profiles: d.profiles.map((p) => (p.account_id === accountId ? { ...p, ...saved } : p)),
      });
      await qc.invalidateQueries({ queryKey: S4S_PROFILES_KEY });
    } catch (e) {
      setError(`Couldn't save: ${message(e)}`);
    } finally {
      setBusy(null);
    }
  }
  return { save, busy, error };
}

export default function S4SSettingPanel({ query, profile }: {
  query: Pick<UseQueryResult<S4SProfiles>, "isPending" | "error">;
  profile: S4SProfile | null;
}) {
  const [managing, setManaging] = useState(false);
  if (query.isPending) return <p className="p-6 text-[14px] text-fg-dim">Loading…</p>;
  if (query.error) return <p role="alert" className="p-6 text-[14px] text-err">{message(query.error)}</p>;
  if (!profile) return <EmptyState kind="creator" text="No creator connected yet" className="py-24" />;
  return managing
    ? <ManagePosts profile={profile} onBack={() => setManaging(false)} />
    : <Settings profile={profile} onManage={() => setManaging(true)} />;
}

function Settings({ profile, onManage }: { profile: S4SProfile; onManage: () => void }) {
  const { save, busy, error } = useSaveProfile(profile.account_id);
  const [limit, setLimit] = useState(String(profile.daily_limit));
  const [creating, setCreating] = useState(false);
  const name = profile.display_name || profile.account_id;
  const primary = profile.posts.find((p) => p.is_primary) ?? null;

  return (
    <section aria-label={`S4S settings for ${name}`} className="max-w-[900px] p-6">
      {error && <p role="alert" className="mb-4 text-[14px] text-err">{error}</p>}

      <div className="flex items-center justify-between">
        <h2 className={HEAD}>Primary post</h2>
        <IfButton className={OUTLINE} onClick={onManage}>Manage posts</IfButton>
      </div>
      <div className={cn(BOX, "mt-[25px]")}>
        {primary ? (
          <div className="relative p-6">
            <span className="absolute left-0 top-0 rounded-tl-lg rounded-br-lg bg-[#2ad4ac] px-2 py-0.5 text-[12px] font-medium text-[#151515]">Primary</span>
            <p className="mt-3 whitespace-pre-wrap break-words text-[14px] text-fg-dim line-clamp-3">{primary.caption}</p>
            <div className="mt-2"><S4SMediaStrip media={primary.media} /></div>
          </div>
        ) : (
          <div className="flex flex-col items-center pt-20 pb-10">
            <IfButton variant="primary" className="h-10 w-[240px] rounded-lg" onClick={() => setCreating(true)}>Create post</IfButton>
            <p className="mt-3 text-[12px] text-[#84818a]">This post will be used for all Share for Share requests</p>
          </div>
        )}
      </div>

      <h2 className={cn(HEAD, "mt-8")}>Limit daily S4S</h2>
      <div className={cn(BOX, "mt-4 p-6")}>
        <p className="text-[14px] text-fg-dim">
          Set the maximum S4S permitted <span className="text-[#ff7c71]">per day</span>. Changes do not affect S4S already scheduled.
        </p>
        <div className="mt-4 flex items-center">
          <IfSelect aria-label="Limit daily S4S" value={limit} options={LIMIT_OPTIONS} onChange={setLimit} className="w-[240px]" />
          <IfButton variant="primary" className="ml-6 w-[76px]" disabled={busy === "limit" || Number(limit) === profile.daily_limit}
            onClick={() => void save("limit", { daily_limit: Number(limit) })}>Save</IfButton>
        </div>
      </div>

      <h2 className={cn(HEAD, "mt-8")}>Discoverability settings</h2>
      <div className="mt-4 space-y-2">
        <div className={ROW}>
          <span>
            <span className="flex items-center gap-2 text-fg">Take part in Share for Share <ExtraTag /></span>
            <span className="block text-[12px]">{OPT_IN_LINE}</span>
          </span>
          <IfSwitch aria-label="Take part in Share for Share" checked={profile.opted_in} loading={busy === "opted_in"}
            onChange={(opted_in) => void save("opted_in", { opted_in })} />
        </div>
        <div className={ROW}>
          <span>{`Allow ${name} to appear on the Discover Creators page`}</span>
          <IfSwitch aria-label="Appear on Discover Creators" checked={profile.discovery_visible} loading={busy === "discovery_visible"}
            onChange={(discovery_visible) => void save("discovery_visible", { discovery_visible })} />
        </div>
      </div>

      <PartnerProfile profile={profile} />
      {creating && <PostModal accountId={profile.account_id} onClose={() => setCreating(false)} />}
    </section>
  );
}

/** Ours: what partners see of the creator, read only: its OnlyFans name, @username and avatar. */
function PartnerProfile({ profile }: { profile: S4SProfile }) {
  return (
    <>
      <h2 className={cn(HEAD, "mt-8 flex items-center gap-2")}>Profile shown to partners <ExtraTag /></h2>
      <div className={cn(BOX, "mt-4 p-6")}>
        <div aria-label="Profile shown to partners" role="group" className="flex items-center gap-3">
          <ProjectionAvatar item={profile} px={44} round />
          <div className="min-w-0">
            <div className="text-[16px] font-semibold text-fg">{profile.display_name || profile.account_id}</div>
            {profile.username && <div className="text-[14px] text-[#999]">@{profile.username}</div>}
          </div>
        </div>
        <p className="mt-3 text-[12px] text-fg-dim">{PARTNER_PROFILE_LINE}</p>
      </div>
    </>
  );
}

/** "Manage posts": the back header, then the post list with Create post; Create / Edit in a pop-up. */
function ManagePosts({ profile, onBack }: { profile: S4SProfile; onBack: () => void }) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState<PostDraft | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [picking, setPicking] = useState<S4SPost | null>(null);
  const full = profile.posts.length >= S4S_MAX_POSTS;
  const acc = profile.account_id;

  function pickMedia(post: S4SPost, ids: number[]) {
    setPicking(null);
    if (ids.length > S4S_MAX_MEDIA) {
      setError(tooMany(ids.length));
      return;
    }
    void run(() => putS4SPostMedia(acc, post.id, ids));
  }

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      await qc.invalidateQueries({ queryKey: S4S_PROFILES_KEY });
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-label="Manage posts" className="p-6">
      <div className="flex items-center justify-between">
        <h2 className={cn(HEAD, "flex items-center gap-2")}>
          <button type="button" aria-label="Back" onClick={onBack} className="grid h-6 w-6 place-items-center text-fg-dim hover:text-accent">
            <ChevronLeft aria-hidden className="h-5 w-5" />
          </button>
          Manage posts
        </h2>
        <span className="flex items-center gap-4">
          <span className="text-[14px] text-fg-dim">{`${profile.posts.length} / ${S4S_MAX_POSTS} S4S posts`}</span>
          <IfButton variant="primary" disabled={full} onClick={() => setEditing({ id: null, caption: "" })}>Create post</IfButton>
        </span>
      </div>
      {error && <p role="alert" className="mt-4 text-[14px] text-err">{error}</p>}
      <div className="mt-4 overflow-x-auto">
        <table aria-label="S4S posts" className={cn(IF_TABLE.table, "min-w-[560px]")}>
          <thead>
            <tr>
              {["Caption", "Media", "Primary", "Actions"].map((h, i) => (
                <th key={h} className={cn(IF_TABLE.th, i < 3 && IF_TABLE.thDivider)}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {profile.posts.length === 0 && (
              <tr><td colSpan={4} className="py-10"><EmptyState size="md" /></td></tr>
            )}
            {profile.posts.map((p) => (
              <tr key={p.id} className={IF_TABLE.row}>
                <td className={cn(IF_TABLE.td, "max-w-[300px] truncate")} title={p.caption}>{p.caption}</td>
                <td className={cn(IF_TABLE.td, "space-y-1")}>
                  <S4SMediaStrip media={p.media} />
                  <IfButton variant="link" disabled={busy} onClick={() => setPicking(p)}>
                    {`Add from Vault (${p.media.length}/${S4S_MAX_MEDIA})`}
                  </IfButton>
                </td>
                <td className={IF_TABLE.td}>
                  {p.is_primary ? (
                    <span className="rounded bg-[#2ad4ac] px-2 py-0.5 text-[12px] font-medium text-[#151515]">Primary</span>
                  ) : (
                    <IfButton variant="link" disabled={busy} onClick={() => void run(() => setPrimaryS4SPost(acc, p.id))}>
                      Set as Primary Post
                    </IfButton>
                  )}
                </td>
                <td className={IF_TABLE.td}>
                  <span className="flex items-center gap-4">
                    <IfButton variant="link" disabled={busy} onClick={() => setEditing(p)}>Edit</IfButton>
                    <IfButton variant="link" disabled={busy} onClick={() => void run(() => deleteS4SPost(acc, p.id))}>Delete</IfButton>
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-[12px] text-fg-dim">
        {`Up to ${S4S_MAX_MEDIA} vault photos or videos per post (no DRM). They are read from this creator's vault when `
          + "a partner posts, so keep them there; the partner who posts them keeps them in their own vault."}
      </p>
      {editing && <PostModal accountId={acc} post={editing} onClose={() => setEditing(null)} />}
      <VaultPicker
        open={picking !== null}
        onClose={() => setPicking(null)}
        accountId={acc}
        fanId={null}
        initialSelectedIds={picking?.media.map((m) => m.vault_media_id) ?? []}
        onConfirm={(picked) => { if (picking) pickMedia(picking, picked.map((m) => m.id)); }}
      />
    </section>
  );
}

type PostDraft = { id: number | null; caption: string; media?: S4SPost["media"] };

/** "Create post" / "Edit Post" at 520: the caption and its count, and up to 5 vault items from "Add from Vault". Save
 *  writes the caption, then the media when they were picked here, as references to this Creator's vault that a
 *  partner's slot reads at post time. While the picker is open it stands in for the pop-up (one dialog at a
 *  time, so Escape and Tab belong to the picker). */
function PostModal({ accountId, post, onClose }: {
  accountId: string;
  post?: PostDraft;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [caption, setCaption] = useState(post?.caption ?? "");
  // The post once it exists: a create whose media save failed retries as an edit of the post it made.
  const [postId, setPostId] = useState<number | null>(post?.id ?? null);
  // null: the media stay as saved.
  const [picked, setPicked] = useState<VaultMedia[] | null>(null);
  const [picking, setPicking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const creating = (post?.id ?? null) == null;
  const fieldId = `s4s-${accountId}-${creating ? "new" : "edit"}`;
  const saved = post?.media ?? [];
  const ids = picked ? picked.map((m) => m.id) : saved.map((m) => m.vault_media_id);

  function pick(list: VaultMedia[]) {
    setPicking(false);
    if (list.length > S4S_MAX_MEDIA) {
      setError(tooMany(list.length));
      return;
    }
    setError(null);
    setPicked(list);
  }

  async function save() {
    setBusy(true);
    setError(null);
    try {
      let id = postId;
      if (id == null) {
        id = (await createS4SPost(accountId, caption)).id;
        setPostId(id);
      } else {
        await editS4SPost(accountId, id, caption);
      }
      if (picked) await putS4SPostMedia(accountId, id, picked.map((m) => m.id));
      await qc.invalidateQueries({ queryKey: S4S_PROFILES_KEY });
      onClose();
    } catch (e) {
      setError(message(e));
      await qc.invalidateQueries({ queryKey: S4S_PROFILES_KEY });
    } finally {
      setBusy(false);
    }
  }

  if (picking) {
    return (
      <VaultPicker open onClose={() => setPicking(false)} accountId={accountId} fanId={null}
        initialSelectedIds={ids} onConfirm={pick} />
    );
  }

  return (
    <IfModal title={creating ? "Create post" : "Edit Post"} width={520} onClose={onClose} footer={(
      <>
        <IfButton onClick={onClose}>Cancel</IfButton>
        <IfButton variant="primary" disabled={busy || !caption.trim()} onClick={() => void save()}>
          {busy && picked?.length ? "Saving media…" : "Save"}
        </IfButton>
      </>
    )}>
      <Field label="Caption" htmlFor={fieldId}>
        <FieldTextarea id={fieldId} rows={5} maxLength={S4S_MAX_CAPTION} value={caption} onChange={(e) => setCaption(e.target.value)} />
      </Field>
      <div className="mt-1 text-[12px] text-fg-dim">{`${caption.length} / ${S4S_MAX_CAPTION}`}</div>
      <div className="mt-4 space-y-2">
        {picked ? (
          picked.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {picked.map((m) => (
                // eslint-disable-next-line @next/next/no-img-element -- a vault thumbnail through the relay
                <img key={m.id} src={vaultTileThumb(m, accountId)} alt="Picked vault media" className="h-10 w-10 rounded object-cover" />
              ))}
            </div>
          )
        ) : (
          <S4SMediaStrip media={saved} />
        )}
        <IfButton variant="link" disabled={busy} onClick={() => setPicking(true)}>
          {`Add from Vault (${ids.length}/${S4S_MAX_MEDIA})`}
        </IfButton>
        <p className="text-[12px] text-fg-dim">
          {`Up to ${S4S_MAX_MEDIA} vault photos or videos (no DRM). Partners post them straight from this creator's vault.`}
        </p>
      </div>
      {error && <p role="alert" className="mt-2 text-[12px] text-err">{error}</p>}
    </IfModal>
  );
}
