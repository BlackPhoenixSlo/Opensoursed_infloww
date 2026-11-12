"use client";

/**
 * CotagSection — the co-performer tag knobs (media_cotag): which co-creator
 * automated media sends @-tag, or no one, and "Always tag videos". CotagForm
 * loads it for Settings › Co-creator tag (CotagTab) and hands the tab its Save (the
 * account-config PUT, `account_ai_config.cotag_*`: every media send of the creator),
 * which the tab puts in its Panel header.
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

import { useEffect, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";

import { IfButton, IfHelp, IfInput, IfLabel, IfSwitch } from "@/components/ui/infloww";
import type { SaveControl } from "@/components/settings/StickySaveBar";
import { useAccountConfig, useSaveAccountConfig } from "@/hooks/useAccountConfig";

import { relay } from "@/lib/relay";
import { Skeleton } from "@/components/ui/Skeleton";

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
    <div className="space-y-4 text-[14px]">
      <div className="max-w-sm">
        <IfLabel htmlFor="cotag-search">Co-creator to tag</IfLabel>
        <div className="mb-2 flex items-center gap-3 text-fg">
          <span data-testid="cotag-pick">{picked ? `@${picked}` : "No co-creator tag"}</span>
          {picked && (
            <IfButton variant="link" onClick={() => pick("")}>Remove</IfButton>
          )}
        </div>
        <IfInput
          id="cotag-search"
          type="search"
          aria-label="Search creators"
          placeholder="Search creators by name or @username"
          className="w-full"
          value={raw}
          onChange={(e) => setRaw(e.target.value)}
        />
        {query && searchQ.isLoading && (
          <IfHelp>Searching…</IfHelp>
        )}
        {query && searchQ.isError && (
          <IfHelp className="text-err">
            Couldn’t search OnlyFans creators. The saved pick is kept.
          </IfHelp>
        )}
        {query && searchQ.isSuccess && found.length === 0 && (
          <IfHelp>No creators found.</IfHelp>
        )}
        {query && found.length > 0 && (
          <ul className="mt-1 rounded-md border border-border divide-y divide-border">
            {found.map((f) => (
              <li key={f.username}>
                <button type="button" className="w-full px-3 py-[5px] text-left text-[14px] text-fg hover:bg-bg-elev-2"
                  onClick={() => pick(f.username)}>
                  @{f.username}{f.name ? ` (${f.name})` : ""}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div
        className="flex items-start gap-3"
        title="For accounts whose videos feature a co-performer. The AI describe for a video is cut from stills, so a POV clip often reads as solo when the co-performer is plainly in it. With this on, every send that attaches a video carries the tag regardless of the describe verdict. Off (the default — most creators are solo), videos follow the describe verdict like photos do."
      >
        <IfSwitch
          aria-label="Always tag videos"
          checked={tagVideos}
          onChange={(v) => onChange({ cotag_tag_videos: v })}
        />
        <div>
          <div className="text-fg">Always tag videos</div>
          <IfHelp className="mt-0">
            Collab accounts: tag every video send, even ones read as solo. Photos follow the describe verdict.
          </IfHelp>
        </div>
      </div>
    </div>
  );
}

/** Loads the creator's config and hands `children` the Save control and the form: Save sends the stored config
 *  back with only the co-tag keys changed (the PUT replaces what it holds, so the rest of the creator's settings
 *  keep theirs). Mount it keyed by the creator, so unsaved edits never carry over to another. */
export function CotagForm({ accountId, children }: {
  accountId: string;
  children: (save: SaveControl, form: ReactNode) => ReactNode;
}) {
  const cfgQ = useAccountConfig(accountId);
  const saveM = useSaveAccountConfig(accountId);
  const [patch, setPatch] = useState<CotagPatch>({});
  const cfg = cfgQ.data?.config;
  const save: SaveControl = {
    onSave: () => { if (cfg) saveM.mutate({ ...cfg, ...patch }, { onSuccess: () => setPatch({}) }); },
    saving: saveM.isPending,
    canSave: !!cfg && Object.keys(patch).length > 0,
    saved: saveM.isSuccess,
    error: saveM.error ? (saveM.error as Error).message || "Save failed" : null,
  };
  let form: ReactNode;
  if (!cfgQ.data?.config) {
    form = cfgQ.isError
      ? <p className="text-sm text-err">{(cfgQ.error as Error)?.message || "Could not load the co-creator tag."}</p>
      // The config read in flight: the form's places as placeholder bars, not a blank card.
      : cfgQ.isLoading
        ? <div role="status" aria-label="Loading" className="space-y-3"><Skeleton className="h-4 w-40" /><Skeleton className="h-10 w-full" /></div>
        : null;
  } else {
    const c = cfgQ.data.config;
    form = (
      <div data-testid="cotag-form">
        <CotagSection
          accountId={accountId}
          tagVideos={patch.cotag_tag_videos ?? c.cotag_tag_videos ?? false}
          username={patch.cotag_username ?? c.cotag_username ?? null}
          onChange={(p) => { setPatch((cur) => ({ ...cur, ...p })); if (!saveM.isIdle) saveM.reset(); }}
        />
      </div>
    );
  }
  return <>{children(save, form)}</>;
}
