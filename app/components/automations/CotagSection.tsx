"use client";

/**
 * CotagSection — the co-performer tag knobs (media_cotag): which co-creator
 * automated media sends @-tag, or no one, and "Always tag videos". CotagCard
 * mounts it on Settings › Co-creator tag (CotagTab) with its own Save (the
 * account-config PUT, `account_ai_config.cotag_*`: every media send of the creator).
 *
 * "Tag a co-creator, which one, or no one" (ticket 85). The co-creator can be
 * any OnlyFans creator: typing searches OF's creators (performers-search, the
 * share dialog's username autocomplete) and a result is the pick, stored as its
 * handle. At send time media_cotag resolves that handle through the account's
 * tagged-friend list, the only ids OF accepts in a message/post tag, so a
 * creator who hasn't accepted the tag yet goes untagged there (logged, never a
 * lost send); a story's @handle overlay needs no list. "No co-creator tag" is
 * the default and hands the form ''. The server stores an own handle as no tag.
 */

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { Button } from "@/components/ui/primitives";
import { useAccountConfig, useSaveAccountConfig, type AccountConfigResp } from "@/hooks/useAccountConfig";

import { relay } from "@/lib/relay";

export interface CotagPatch {
  cotag_tag_videos?: boolean;
  cotag_username?: string;
}

/** One row of OF's performers-search. */
interface FoundCreator {
  id: number | string;
  name?: string | null;
  username?: string | null;
}

const DEBOUNCE_MS = 250;

const inputCls =
  "w-full rounded-lg bg-bg-elev-1 border border-border text-sm px-2 py-1.5 text-fg focus:outline-none focus:ring-2 focus:ring-accent/40";

export default function CotagSection({ accountId, tagVideos, username, onChange }: {
  accountId: string | null;
  tagVideos: boolean;
  /** Stored handle, no '@'. null / '' = No co-creator tag. */
  username: string | null;
  onChange: (patch: CotagPatch) => void;
}) {
  const [raw, setRaw] = useState("");
  const [query, setQuery] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setQuery(raw.trim().replace(/^@/, "")), DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [raw]);
  const searchQ = useQuery<FoundCreator[]>({
    queryKey: ["performers-search", accountId, query],
    enabled: !!accountId && !!query,
    queryFn: () => relay.get<FoundCreator[] | { list?: FoundCreator[] }>(
      `/api/of/v2/users/performers-search?query=${encodeURIComponent(query)}&limit=10`,
      { accountId: accountId ?? undefined },
    ).then((r) => (Array.isArray(r) ? r : (r?.list ?? []))),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });
  const found = (searchQ.data ?? [])
    .map((u) => ({ username: (u.username ?? "").toLowerCase(), name: u.name ?? "" }))
    .filter((f) => f.username);
  const picked = (username ?? "").toLowerCase();
  const pick = (handle: string) => {
    onChange({ cotag_username: handle });
    setRaw("");
    setQuery("");
  };

  return (
    <div className="space-y-2">
      <span className="text-[11px] uppercase tracking-wide text-fg-dim">
        Co-performer tag
      </span>
      <p className="text-[11px] text-fg-dim">
        Pick the co-creator automated sends @-tag (OF’s release-form rule) whenever the
        attached media isn’t provably solo, or no one. Search any OnlyFans creator. Messages
        and posts carry the tag once the creator has accepted this account’s tag request;
        stories show the @handle either way.
      </p>
      <div className="space-y-1 max-w-xs">
        <span className="block text-[11px] text-fg-dim">Co-creator to tag</span>
        <div className="flex items-center gap-2 text-sm text-fg">
          <span data-testid="cotag-pick">{picked ? `@${picked}` : "No co-creator tag"}</span>
          {picked && (
            <button type="button" className="text-[11px] text-fg-dim underline"
              onClick={() => pick("")}>
              Remove
            </button>
          )}
        </div>
        <input
          type="search"
          aria-label="Search creators"
          placeholder="Search creators by name or @username"
          className={inputCls}
          value={raw}
          onChange={(e) => setRaw(e.target.value)}
        />
        {query && searchQ.isLoading && (
          <span className="block text-[11px] text-fg-dim">Searching…</span>
        )}
        {query && searchQ.isError && (
          <span className="block text-[11px] text-err">
            Couldn’t search OnlyFans creators. The saved pick is kept.
          </span>
        )}
        {query && searchQ.isSuccess && found.length === 0 && (
          <span className="block text-[11px] text-fg-dim">No creators found.</span>
        )}
        {query && found.length > 0 && (
          <ul className="rounded-lg border border-border divide-y divide-border">
            {found.map((f) => (
              <li key={f.username}>
                <button type="button" className="w-full px-2 py-1.5 text-left text-sm text-fg hover:bg-bg-elev-1"
                  onClick={() => pick(f.username)}>
                  @{f.username}{f.name ? ` (${f.name})` : ""}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
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
