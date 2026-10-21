"use client";

/**
 * CotagSection — the co-performer tag knobs (media_cotag): which co-creator
 * automated media sends @-tag, or no one, and "Always tag videos". CotagCard
 * mounts it on Settings › Co-creator tag (CotagTab) with its own Save (the
 * account-config PUT, `account_ai_config.cotag_*`: every media send of the creator).
 *
 * "Tag a co-creator, which one, or no one" (ticket 85). The pick list is this
 * account's OF tagged-friend list — the same call the chat composer's tag
 * picker makes, and the only ids OF accepts in a tag — so a pick can't be a
 * handle OF refuses. "No co-creator tag" is the default and hands the form ''.
 * An account never appears on its own list, and the server stores an own
 * handle as no tag.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { Button } from "@/components/ui/primitives";
import { useAccountConfig, useSaveAccountConfig, type AccountConfigResp } from "@/hooks/useAccountConfig";

import { relay, type TaggedFriendUsersResp } from "@/lib/relay";

export interface CotagPatch {
  cotag_tag_videos?: boolean;
  cotag_username?: string;
}

const selectCls =
  "w-full rounded-lg bg-bg-elev-1 border border-border text-sm px-2 py-1.5 text-fg focus:outline-none focus:ring-2 focus:ring-accent/40";

export default function CotagSection({ accountId, tagVideos, username, onChange }: {
  accountId: string | null;
  tagVideos: boolean;
  /** Stored handle, no '@'. null / '' = No co-creator tag. */
  username: string | null;
  onChange: (patch: CotagPatch) => void;
}) {
  const friendsQ = useQuery<TaggedFriendUsersResp>({
    queryKey: ["tagged-friend-users", accountId, "cotag"],
    enabled: !!accountId,
    // 50 is the relay route's cap (`limit` le=50; more is a 422). One page:
    // a creator's accepted co-performers are a handful.
    queryFn: () => relay.get<TaggedFriendUsersResp>(
      "/api/of/v2/posts/tagged-friend-users?limit=50&offset=0",
      { accountId: accountId ?? undefined }),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });
  const friends = (friendsQ.data?.items ?? [])
    .map((u) => ({ username: (u.user?.username ?? "").toLowerCase(),
                   name: u.user?.name ?? u.name ?? "" }))
    .filter((f) => f.username);
  const picked = (username ?? "").toLowerCase();
  const onList = friends.some((f) => f.username === picked);

  return (
    <div className="space-y-2">
      <span className="text-[11px] uppercase tracking-wide text-fg-dim">
        Co-performer tag
      </span>
      <p className="text-[11px] text-fg-dim">
        Pick the co-creator automated sends @-tag (OF’s release-form rule) whenever the
        attached media isn’t provably solo, or no one. The list is this account’s
        OnlyFans tagged-friend list: a co-creator appears once they have accepted this
        account’s tag request.
      </p>
      <label className="block space-y-1 max-w-xs">
        <span className="text-[11px] text-fg-dim">Co-creator to tag</span>
        <select
          aria-label="Co-creator to tag"
          className={selectCls}
          value={picked}
          onChange={(e) => onChange({ cotag_username: e.target.value })}
        >
          <option value="">No co-creator tag</option>
          {picked && !onList && (
            // Only a loaded list can say a pick is off it; until then it shows plain.
            <option value={picked}>
              @{picked}{friendsQ.isSuccess
                ? " (not on this account’s tagged-friend list, won’t tag)" : ""}
            </option>
          )}
          {friends.map((f) => (
            <option key={f.username} value={f.username}>
              @{f.username}{f.name ? ` (${f.name})` : ""}
            </option>
          ))}
        </select>
        {friendsQ.isLoading && (
          <span className="block text-[11px] text-fg-dim">Loading co-creators…</span>
        )}
        {friendsQ.isError && (
          <span className="block text-[11px] text-err">
            Couldn’t load this account’s co-creators from OnlyFans. The saved pick is kept.
          </span>
        )}
      </label>
      <label
        className="flex items-start gap-2 text-sm text-fg"
        title="For accounts whose videos feature a co-performer. The AI describe for a video is cut from stills, so a POV clip often reads as solo when the co-performer is plainly in it. With this on, every send that attaches a video carries the tag regardless of the describe verdict. Off (the default — most creators are solo), videos follow the describe verdict like photos do."
      >
        <input
          type="checkbox"
          className="mt-0.5"
          checked={tagVideos}
          onChange={(e) => onChange({ cotag_tag_videos: e.target.checked })}
        />
        <span>
          Always tag videos
          <span className="block text-[11px] text-fg-dim">
            For collab accounts: tag every video send, even ones the AI describe
            read as solo. Photos still follow the describe verdict.
          </span>
        </span>
      </label>
    </div>
  );
}

/** The section on its own card: loads the account config and saves the stored
 *  config back with only the co-tag keys changed (the PUT replaces what it
 *  holds, so the rest of the creator's settings keep theirs). */
export function CotagCard({ accountId }: { accountId: string }) {
  const cfgQ = useAccountConfig(accountId);
  if (!cfgQ.data?.config) {
    return cfgQ.isError
      ? <p className="text-sm text-err">{(cfgQ.error as Error)?.message || "Could not load the co-creator tag."}</p>
      : null;
  }
  return <CotagForm accountId={accountId} resp={cfgQ.data} />;
}

function CotagForm({ accountId, resp }: { accountId: string; resp: AccountConfigResp }) {
  const saveM = useSaveAccountConfig(accountId);
  const [patch, setPatch] = useState<CotagPatch>({});
  const cfg = resp.config;
  const dirty = Object.keys(patch).length > 0;
  return (
    <div data-testid="cotag-card" className="rounded-lg border border-border p-3 space-y-2 text-sm">
      <CotagSection
        accountId={accountId}
        tagVideos={patch.cotag_tag_videos ?? cfg.cotag_tag_videos ?? false}
        username={patch.cotag_username ?? cfg.cotag_username ?? null}
        onChange={(p) => { setPatch((cur) => ({ ...cur, ...p })); if (!saveM.isIdle) saveM.reset(); }}
      />
      <div className="flex items-center gap-2">
        <Button size="sm" disabled={!dirty || saveM.isPending}
          onClick={() => saveM.mutate({ ...cfg, ...patch }, { onSuccess: () => setPatch({}) })}>
          {saveM.isPending ? "Saving…" : "Save co-creator tag"}
        </Button>
        {saveM.isError && <p className="text-sm text-err">{saveM.error.message || "Save failed"}</p>}
        {saveM.isSuccess && !dirty && <p role="status" className="text-sm text-ok">Saved.</p>}
      </div>
    </div>
  );
}
