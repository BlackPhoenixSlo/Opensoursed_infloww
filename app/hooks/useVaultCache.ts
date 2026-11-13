"use client";

/**
 * useVaultCache — the local whole-vault mirror ("Collect all").
 *
 *   summary  → GET  /admin/vault-ai/cache/summary   {count, running, complete, last_run}
 *   collect  → POST /admin/vault-ai/collect          starts a sweep
 *   status   → GET  /admin/vault-ai/collect/status   progress (polled while running)
 *   items    → GET  /admin/vault-ai/items            read the mirror (instant local search)
 *
 * The mirror read returns the SAME {list, hasMore} shape as /api/of/v2/vault/media
 * (each item is the raw OF media dict + an `_ai` overlay), so the grid + <VaultTile/>
 * consume it unchanged — search is a local LIKE-scan, no OF round-trip.
 */

import { infiniteQueryOptions, useInfiniteQuery, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

import type { TagFolderPayload } from "@/components/vault/tagFolderForm";
import { folderSortAfter, loadFolderSort, saveFolderSort, type FolderSortState } from "@/components/vault/vaultFolderSort";
import type { PlanChanges } from "@/components/vault/vaultAiFoldersForm";
import { useSweepStatus } from "@/hooks/useVaultSweep";
import { vaultListsKey, vaultMediaKey } from "@/hooks/useVaultMedia";
import { relay, type VaultMedia } from "@/lib/relay";
import { type FanId } from "@/lib/fanId";
import { flushPersistedCache } from "@/lib/rqPersister";
import { errText } from "@/lib/errText";
import { invalidateVaultQueries } from "@/lib/vaultInvalidation";

// Lazy-load in small chunks on scroll (not all at once — 244 images loading
// simultaneously is what made the grid slow). Infinite-scroll fetches the next
// page as the sentinel enters view.
const PAGE = 40;

/** Push ONE hand-made internal folder out as a real OF vault list.
 *  Additive: `stale_on_of` lists ids OF still holds that the folder no longer
 *  does — clearing those needs a delete+recreate, which mints a new list id. */
export async function publishFolderToOf(accountId: string, folderId: number) {
  return relay.post<PublishFolderResult>(
    `/admin/vault-ai/folders/${folderId}/publish`,
    { account_id: accountId },
    { accountId },
  );
}

export interface PublishFolderResult {
  folder_id: number;
  name: string;
  of_list_id: number;
  created: boolean;
  pushed: number;
  /** A pack's free rung only: members left out because Jev says they may not ride free. */
  skipped_unsafe?: number[];
  /** Any pack rung: clips / gifs filed before photos-only, left out (a pack is photos only). */
  skipped_videos?: number[];
  synced: number;
  stale_on_of: number[];
}

// ── The pack picker ────────────────────────────────────────────────

export interface PackCandidate {
  media_id: number;
  kind: string;
  /** The rung it is filed on now, or null if unruled. */
  rung: string | null;
  /** The rung Jev's tier + covering answer suggest (a prefill to confirm, never saved by itself), or null. */
  suggested: string | null;
  /** Her body's price tier from Jev: 100 inserted, 50 labia visible, 10 topless, 0 none; null unknown / no Jev. */
  tier: number | null;
  /** How likely the category is the subject, 0..1 (confident: >= .6, possible: .3 to .6); most likely first. */
  score: number;
  /** A Jev v8 photo (`_jev`): every unfiled candidate; false only for a row filed before the precision rule. */
  jev?: boolean;
  /** Jev sees the part but scores it .3 <= score < the preselect gate: shown unticked after the confident ones,
   *  `suggested` from the same tier + covering rule without the gate. Check it before filing. */
  possible?: boolean;
  /** May ride the free (cheapest) rung: false = Jev says her body may be on show (the server refuses it there);
   *  null = no Jev answer, the operator decides. */
  free_ok?: boolean | null;
  /** Jev says feet are the subject (score >= FEET_PRESELECT_SCORE) and `suggested` is safe: the tile arrives ticked
   *  for "File N preselected". */
  preselect?: boolean;
  /** Filed on the free rung although `free_ok` is false (filed before the guard): publish skips it; unfile it. */
  unsafe_on_free?: boolean;
  /** Enough to reject on text alone, before any pixel is fetched. */
  description: string;
}

/** One rung of the ladder. `folder_id` is null until the first Save creates it,
 *  so the ladder's shape never depends on how far triage has got. */
export interface PackRung {
  rung: string;
  name: string;
  folder_id: number | null;
  count: number;
  of_list_id: number | null;
}

export interface PackCandidates {
  category: string;
  rungs: string[];
  folders: PackRung[];
  candidates: PackCandidate[];
  filed: number;
}

export function usePackCandidates(accountId: string | null, category: string, enabled = true) {
  return useQuery<PackCandidates>({
    queryKey: ["vault-pack-candidates", accountId, category],
    enabled: !!accountId && enabled,
    queryFn: () =>
      relay.get(
        `/admin/vault-ai/pack-candidates?account_id=${encodeURIComponent(accountId!)}` +
          `&category=${encodeURIComponent(category)}`,
      ),
    // The operator's own Save is the only thing that changes this.
    staleTime: 60_000,
  });
}

export interface PackTriageResult {
  category: string;
  saved: number;
  rejected: number;
  folders: PackRung[];
}

export async function savePackTriage(
  accountId: string,
  category: string,
  verdicts: { media_id: number; rung: string | null }[],
) {
  return relay.post<PackTriageResult>(
    `/admin/vault-ai/pack-triage`,
    { account_id: accountId, category, verdicts },
    { accountId },
  );
}

/** Create a REAL OF vault folder (+ optionally add media). */
export async function createOfFolder(accountId: string, name: string, mediaIds: FanId[] = []) {
  return relay.post(
    `/admin/vault-ai/of-folders`,
    { account_id: accountId, name, media_ids: mediaIds },
    { accountId },
  );
}

/** Add media to a REAL OF folder (by OF list id). */
export async function addToOfFolder(accountId: string, listId: FanId, mediaIds: FanId[]) {
  return relay.post(
    `/admin/vault-ai/of-folders/${encodeURIComponent(String(listId))}/add`,
    { account_id: accountId, media_ids: mediaIds },
    { accountId },
  );
}

/** Take media out of a REAL OF folder (by OF list id); they stay in the vault. */
export async function removeFromOfFolder(accountId: string, listId: FanId, mediaIds: FanId[]) {
  return relay.post(
    `/admin/vault-ai/of-folders/${encodeURIComponent(String(listId))}/remove`,
    { account_id: accountId, media_ids: mediaIds },
    { accountId },
  );
}

export async function renameOfFolder(accountId: string, listId: FanId, name: string) {
  return relay.post(
    `/admin/vault-ai/of-folders/${encodeURIComponent(String(listId))}/rename`,
    { account_id: accountId, name },
    { accountId },
  );
}

export async function deleteOfFolder(accountId: string, listId: FanId) {
  return relay.delete(
    `/admin/vault-ai/of-folders/${encodeURIComponent(String(listId))}?account_id=${encodeURIComponent(accountId)}`,
    { accountId },
  );
}

/** Set OF folder-list order: {sort,order} or a manual {customOrder:[ids]}. Once OF took it, the folder sort label
 *  (vaultFolderSort.ts `folderSortAfter`) is saved and returned: the one label, whichever page sorted. */
export async function sortOfFolders(
  accountId: string,
  opts: { sort?: string; order?: string; customOrder?: readonly FanId[] },
): Promise<FolderSortState> {
  await relay.post(
    `/admin/vault-ai/of-folders/sort`,
    { account_id: accountId, sort: opts.sort, order: opts.order, custom_order: opts.customOrder },
    { accountId },
  );
  const saved = folderSortAfter(loadFolderSort(accountId), opts);
  saveFolderSort(accountId, saved);
  return saved;
}

export interface OfFolderMirror {
  /** Folder id — FanId, matching VaultList.id (Fansly albums are snowflakes). */
  id: FanId;
  name: string;
  type: string;
  photosCount: number;
  videosCount: number;
  gifsCount: number;
  audiosCount: number;
  hasMedia: boolean;
  mediaCount: number;
  builtin: boolean;
}

/** OF folders derived from the local mirror's per-item listStates. Accurate
 *  where OF's live vault/lists lies (bogus hasMedia) or drops a folder
 *  entirely (e.g. a freshly-touched one). Non-empty folders only — the panel
 *  unions this with the live list to also show empty folders. */
export function ofFoldersMirrorKey(accountId: string | null) {
  return ["vault-of-folders-mirror", accountId] as const;
}

export function useOfFoldersMirror(accountId: string | null, enabled = true) {
  return useQuery<{ list: OfFolderMirror[] }>({
    queryKey: ofFoldersMirrorKey(accountId),
    enabled: enabled && !!accountId,
    queryFn: () =>
      relay.get(`/admin/vault-ai/of-folders?account_id=${encodeURIComponent(accountId!)}`),
    staleTime: 60_000,
  });
}

/** One item's describe result. `ok` false carries `status` — the reason, which
 *  the row is stamped with (`refused`, `blocked_drm`, `fetch_failed`, …) — plus
 *  `detail`, the sentence to show a human. `capped` is the one an operator can
 *  act on: it means today's AI budget is spent, nothing was attempted, and the
 *  item is untouched. The rest of the payload is the AI fields the caller
 *  merges into the row it already holds. */
export interface DescribeResult extends Record<string, unknown> {
  media_id: number;
  ok: boolean;
  status: "described" | "capped" | "refused" | "error" | string;
  detail?: string;
}

export async function describeMedia(
  accountId: string, mediaId: number,
): Promise<DescribeResult> {
  return relay.post<DescribeResult>(
    `/admin/vault-ai/describe`,
    { account_id: accountId, media_id: mediaId },
    { accountId },
  );
}

/** Which bake-off prompt a describe pass uses.
 *  v2 = rich structured schema (acts / clothing_state / beats / primary_folder)
 *       — what auto-foldering needs. ~0.04¢ an item.
 *  v1 = the original one-sentence prompt, ~4× cheaper, no structured fields. */
export type PromptVersion = "v1" | "v2";

/** The start body for a describe pass. Posted by `useVaultSweep`, which owns
 *  every sweep's start call — this is only the shape of what describe adds on
 *  top of `account_id`. */
export function describeAllBody(opts: {
  force?: boolean;
  /** Re-scan rows produced by a DIFFERENT prompt version (resumable). */
  restage?: boolean;
  promptVersion?: PromptVersion;
  model?: string;
}): Record<string, unknown> {
  return {
    force: !!opts.force,
    restage: !!opts.restage,
    prompt_version: opts.promptVersion ?? "v2",
    ...(opts.model ? { model: opts.model } : {}),
  };
}

/** Today's spend against this account's daily LLM cap, for the VISION provider
 *  (describe + flags both bill there). The cap is per-(account, provider), so
 *  this is the budget a describe sweep actually spends — a busy chat day does
 *  not close describe down, and vice versa.
 *
 *  `capped` is the money, not the rollup row's sticky `is_capped` flag: raising
 *  the cap mid-day makes calls succeed again while that flag stays set.
 *
 *  `blocked_reason` is the server's own sentence, already formatted, and is the
 *  ONLY thing the UI should show. Composing it here as well would give one
 *  sentence two authors in two languages. Empty exactly when nothing blocks. */
export interface VisionCapState {
  day: string;
  provider: string;
  cap_millicents: number;
  spent_millicents: number;
  remaining_millicents: number;
  capped: boolean;
  /** The cap was hit at some point today, even if it has since been raised. */
  flagged: boolean;
  blocked_reason: string;
}

/** What each sweep mode would actually process — real counts for the UI. */
export function useDescribePlan(accountId: string | null, promptVersion: PromptVersion) {
  return useQuery<{
    total: number;
    undescribed: number;
    restage: number;
    prompt_version: PromptVersion;
    /** Absent only against a relay that predates the cap gate. */
    cap?: VisionCapState;
    /** Whether Jev v8 (every photo's flags + describe) can run on this server (absent on an older relay). */
    jev?: { ready: boolean; reason: string };
  }>({
    queryKey: ["vault-describe-plan", accountId, promptVersion],
    enabled: !!accountId,
    queryFn: () =>
      relay.get(
        `/admin/vault-ai/describe-all/plan?account_id=${encodeURIComponent(accountId!)}` +
          `&prompt_version=${promptVersion}`,
      ),
    staleTime: 30_000,
  });
}

// ── AI folder plan ────────────────────────────────────────────────
//
// The vault's "Build AI folders" button. Two steps, deliberately: the plan is
// a free read-only preview, and NOTHING is created until the operator confirms.
// The apply call re-derives the plan server-side rather than posting the
// previewed ids back, so a preview left open for ten minutes can't write a
// stale grouping.

export interface AiFolderItem {
  media_id: number;
  kind: string;
  manual_order: number;
  score: number | null;
  tier: string;
  closes: boolean;
  clothing_state: string;
  /** Scripts only: a closer borrowed from outside the shoot (it had none of its own). */
  borrowed?: boolean;
}

export interface AiFolder {
  name: string;
  source: "script" | "lane" | "topic";
  purpose: string;
  size: number;
  kinds: Record<string, number>;
  tiers: Record<string, number>;
  closes_on_own: number;
  items: AiFolderItem[];
  outfit?: string;
  mixed?: boolean;
  /** Scripts only: the room the part was shot in ('' when unknown), and what to know before sending it
   *  ("no closer", "borrowed closer", "photos only", "rungs 1–2", "capped from 50"…); [] when clean. */
  room?: string;
  health?: string[];
  lane?: string;
  /** A `-solo` cut of the lane it is named after — same lane, minus everyone
   *  else. Every folder carries this, so nothing has to test for its presence;
   *  `solo_of` is the size of the lane it was cut from ("12 of 34"), and is
   *  null exactly when `solo` is false. */
  solo: boolean;
  solo_of: number | null;
  /** What Confirm does with it: make a new folder, or refresh the generated one of this name. */
  change: "new" | "keep";
  /** Topic folders only: the topic slug and its price split ("free" | "$10" | "$50" | "$100", explicit topics
   *  "$50" | "$100" | "$150"); null when the plan was built with `split` off (one folder per topic). */
  topic?: string;
  price?: string | null;
}

/** One opt-in Jev topic (`service/vault_topic_folders.py`) and how many items (photos + clips) it holds across its
 *  price splits, ticked or not. `price`: "split" (free/$10/$50/$100), "explicit" ($50/$100/$150, never free),
 *  "free" (free only). */
export interface AiFolderTopic {
  slug: string;
  name: string;
  description: string;
  price: "split" | "explicit" | "free";
  count: number;
}

export interface AiFolderPlan {
  account_id: string;
  keep: number;
  solo: boolean;
  /** The topic slugs this plan was built with (catalogue order). */
  topics: string[];
  /** Topic folders split by price (false = one `AI-<topic>` folder each). */
  split: boolean;
  shoots_found: number;
  folders: AiFolder[];
  /** Every topic, ticked or not, with its size. */
  topic_catalogue: AiFolderTopic[];
  /** Jev on for the account, and how many of the planned items (photos + clips) carry a current Jev answer. */
  jev: { enabled: boolean; items: number; with_jev: number };
  /** What Confirm does to the AI- folders already there, by the same match the apply makes. `keep` counts folders
   *  (not the shoot count above); `retire_on_of` = retired ones bound to an OF list (unlinked, never deleted on OF). */
  changes: PlanChanges;
  /** Duplicate copies left out: each Duplicates set is planned as its kept item only. */
  dupes_collapsed: number[];
  summary: {
    folders: number;
    scripts: number;
    /** Lanes NOT counting their solo cuts. */
    lanes: number;
    solo_cuts: number;
    topics: number;
    unique_media: number;
    memberships: number;
    dupes_collapsed: number;
  };
  /** Only computed when `solo` was asked for. `is_solo` refuses to call an item
   *  solo without the evidence (`people_count` / `partner_visible`, both V2
   *  describe fields), so on a V1-described vault the solo folders come out
   *  empty — correctly, and unreadably. This is what says why. */
  solo_coverage: {
    described: number;
    known: number;
    unknown: number;
    solo: number;
    ready: boolean;
  } | null;
  /** Coverage of the cheap pussy/breasts flags pass. When `ready` is false the
   *  paid tiers silently fall back to `clothing_state`, which was measured
   *  wrong on ~1 in 3 of the stills the $50 tier is built from — so the folders
   *  come out quietly wrong rather than visibly broken. Run /flags-all first. */
  flags: { stills: number; flagged: number; missing: number; ready: boolean };
}

export interface VaultFlagsStatus {
  running: boolean;
  progress: {
    total: number;
    done: number;
    failed: number;
    capped: boolean;
    cost_millicents: number;
    error?: string;
  } | null;
  coverage: { stills: number; flagged: number; missing: number; ready: boolean };
}

/** START the cheap exposure pass over an account's stills AND clips (~3s/item,
 *  ~$0.001 per 100). Enrichment only — merges the flags into each row and
 *  rewrites nothing else. Required before the paid tease tiers can be trusted.
 *
 *  Returns as soon as the sweep is queued. A whole vault takes minutes, which no
 *  proxy will hold a socket open for — waiting on the response is what showed
 *  "Internal Server Error" while the sweep ran on regardless. Poll
 *  `useVaultFlagsStatus` for progress. */
export async function runVaultFlags(accountId: string) {
  return relay.post<{ status: string; candidates: number; already: boolean }>(
    `/admin/vault-ai/flags-all`, { account_id: accountId }, { accountId },
  );
}

/** Poll the sweep while it runs. `coverage` comes from the DB, so a relay
 *  restart mid-sweep shows where the vault really stands rather than zero.
 *
 *  `pollWhileIdle` preserves this caller's own semantics: the folders modal arms
 *  the watch on the click and needs the poll running BEFORE the server admits
 *  the sweep exists, because it stops watching on the first landed answer that
 *  says `running: false` (see VaultAiFoldersModal's `since`). Self-arming would
 *  make that first answer arrive only after the sweep had already started. */
export function useVaultFlagsStatus(accountId: string | null, enabled: boolean) {
  return useSweepStatus<VaultFlagsStatus>("flags-all", accountId, {
    enabled,
    pollWhileIdle: enabled,
  });
}

/** What a folder plan is cut from: how many shoots stay whole, and whether the
 *  lanes also get their solo cut. Named rather than positional — these are two
 *  booleans and an int in a row, and at a call site `(id, 2, true, false)` is
 *  a bug waiting to be written. */
export interface FolderPlanOptions {
  keep?: number;
  /** Add a `-solo` cut of each lane, keeping only the items nobody else is in. */
  solo?: boolean;
  /** Jev topic slugs to add as topic folders (none = no topic folders). */
  topics?: string[];
  /** Split topic folders by price (default true); false = one `AI-<topic>` folder each. */
  split?: boolean;
}

/** Preview the folders the pipeline would create. Read-only — creates nothing.
 *
 *  The options are part of the query key because they are part of what the plan
 *  IS, and the SAME options have to reach `applyAiFolders` (see there). */
export function useAiFolderPlan(
  accountId: string | null,
  { keep = 2, solo = false, topics = [], split = true }: FolderPlanOptions = {},
  enabled = false,
) {
  const topicsParam = topics.join(",");
  return useQuery<AiFolderPlan>({
    queryKey: ["vault-ai-folder-plan", accountId, keep, solo, topicsParam, split],
    enabled: !!accountId && enabled,
    queryFn: () =>
      relay.get(
        `/admin/vault-ai/folder-plan?account_id=${encodeURIComponent(accountId!)}&keep=${keep}` +
          `&solo=${solo ? "true" : "false"}&split=${split ? "true" : "false"}` +
          (topicsParam ? `&topics=${encodeURIComponent(topicsParam)}` : ""),
      ),
    staleTime: 30_000,
  });
}

export interface ApplyAiFoldersResult {
  folders: number;
  new: number;
  reused: number;
  items: number;
  of_mirrored?: number;
  of_failed?: number;
  created: {
    folder_id: number;
    name: string;
    items: number;
    reused: boolean;
    of_list_id?: number;
    of_error?: string;
  }[];
}

/** Create the previewed folders. `confirm` is required server-side, so there is
 *  no single-click path from browsing to writing. Re-running refreshes the same
 *  `AI-` folders instead of duplicating them, and never touches a folder the
 *  operator made by hand.
 *
 *  `mirrorToOf` additionally creates them as REAL OF vault lists — the only
 *  write to her OnlyFans account in this flow, hence a separate flag rather
 *  than something `confirm` implies. Nothing is ever sent either way.
 *
 *  The plan options MUST match what the preview was showing. The server
 *  re-derives the plan and retires generated folders the current plan no longer
 *  makes, so applying without `solo` after previewing with it would create the
 *  lanes and delete every `-solo` folder in the same call. */
export async function applyAiFolders(
  accountId: string,
  { keep = 2, solo = false, mirrorToOf = false, topics = [], split = true }:
    FolderPlanOptions & { mirrorToOf?: boolean } = {},
): Promise<ApplyAiFoldersResult> {
  return relay.post(
    `/admin/vault-ai/folder-plan/apply`,
    { account_id: accountId, keep, confirm: true, mirror_to_of: mirrorToOf, solo, topics, split },
    { accountId },
  );
}

/** One item awaiting the operator's eye. Pre-set to what the model believes;
 *  the operator taps only what is wrong. */
export interface FlagsReviewItem {
  media_id: number;
  kind: string;
  /** Why the system nominated this for a human look; empty = it did not. */
  iffy: string[];
  iffy_why: string[];
  lanes: string[];
  regions: Record<string, string>;
  over: Record<string, string>;
  description: string;
  clothing_state: string;
  explicitness: string;
  codes: string[];
  /** How the lanes and copy read it while the two passes disagree (auto-settled,
   *  never written); empty when they agree. */
  settled: string[];
  /** The tease price that reading put on it ($50 / $10 / 0); the queue sorts disputed items by it. */
  settled_price: number;
  /** Regions already corrected by hand and frozen against re-runs. */
  locked: string[];
  graded: { v?: number; corrected?: string[]; note?: string };
}

export function useFlagsReview(
  accountId: string | null,
  enabled = false,
  onlyIffy = false,
  limit = 200,
) {
  return useQuery<{
    prompt_version: number;
    total: number;
    graded: number;
    iffy: number;
    only_iffy: boolean;
    items: FlagsReviewItem[];
  }>({
    queryKey: ["vault-flags-review", accountId, limit, onlyIffy],
    enabled: !!accountId && enabled,
    queryFn: () =>
      relay.get(
        `/admin/vault-ai/flags-review?account_id=${encodeURIComponent(accountId!)}` +
          `&limit=${limit}&only_iffy=${onlyIffy}`,
      ),
    staleTime: 15_000,
  });
}

export function useFlagsAccuracy(accountId: string | null, enabled = false) {
  return useQuery<{
    prompt_version: number;
    graded_items: number;
    graded_other_versions: number;
    answers: number;
    accuracy: number | null;
    per_region: Record<string, { ok: number; n: number }>;
  }>({
    queryKey: ["vault-flags-accuracy", accountId],
    enabled: !!accountId && enabled,
    queryFn: () =>
      relay.get(`/admin/vault-ai/flags-accuracy?account_id=${encodeURIComponent(accountId!)}`),
    staleTime: 15_000,
  });
}

/** Record one verdict. Corrections are locked permanently; everything left
 *  alone is recorded as CONFIRMED — which is not a no-op, it is the evidence
 *  the accuracy number runs on. Without it, "looked and agreed" and "never
 *  opened" are the same record. */
export async function gradeFlags(
  accountId: string,
  mediaId: number,
  corrections: Record<string, string>,
  note = "",
): Promise<{ ok: boolean; corrected: string[]; confirmed: string[] }> {
  return relay.post(
    `/admin/vault-ai/flags-review/grade`,
    { account_id: accountId, media_id: mediaId, corrections, note },
    { accountId },
  );
}

/** Harvest OF's own vault search for `query` and fold it into our index, so
 *  local search becomes a superset of OF's. Cached server-side after first run. */
export async function searchOf(
  accountId: string,
  query: string,
): Promise<{ ids: number[]; count: number; source: string }> {
  return relay.post(`/admin/vault-ai/search-of`, { account_id: accountId, query }, { accountId });
}

/** OF's own vault search for `query`, harvested into the mirror (`searchOf`), then the mirror grid refetched with
 *  it. True while either is in flight: the grid shows "Searching OnlyFans…", never "No data", until OF answered.
 *  `enabled`: the grid reads the mirror (the harvest only tags media it holds). Per account+query; 10 min in memory, never persisted (not on the allowlist), the relay TTL-caches OF's side. */
export function useOfSearch(accountId: string | null, query: string, enabled: boolean): boolean {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["vault-search-of", accountId, query] as const,
    queryFn: async () => {
      const r = await searchOf(accountId as string, query);
      await qc.invalidateQueries({ queryKey: mirrorItemsKey(accountId) });
      return r;
    },
    enabled: enabled && !!accountId && !!query,
    staleTime: 10 * 60 * 1000,
    gcTime: 10 * 60 * 1000,
    retry: false,
    refetchOnWindowFocus: false,
  });
  return q.isFetching;
}

export async function reorderItems(
  accountId: string,
  folderId: FanId | null,
  order: { media_id: number; manual_order: number | null }[],
) {
  return relay.post(
    `/admin/vault-ai/reorder`,
    { account_id: accountId, folder_id: folderId, order },
    { accountId },
  );
}

export interface VaultCacheSummary {
  account_id: string;
  count: number;
  running: boolean;
  /** True once a full background walk or a manual Collect finished. Missing → false:
   *  a partial mirror must not switch the picker to the DB path. */
  complete?: boolean;
  /** `total_seen` is null for a restricted chatter (whole-vault count). */
  last_run: { id: number; status: string; total_seen: number | null; finished_at: string | null } | null;
}

export interface CollectRun {
  id: number;
  status: string;
  phase: string | null;
  /** Whole-vault totals: null for a restricted chatter (they would leak folder sizes it may not see). */
  total_seen: number | null;
  upserted: number | null;
  pages_done: number | null;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  running: boolean;
}

/** Poll while a sweep is running so the button shows live progress. */
export function cacheSummaryKey(accountId: string | null) {
  return ["vault-cache-summary", accountId] as const;
}

export function useVaultCacheSummary(accountId: string | null) {
  return useQuery<VaultCacheSummary>({
    queryKey: cacheSummaryKey(accountId),
    enabled: !!accountId,
    queryFn: () =>
      relay.get<VaultCacheSummary>(
        `/admin/vault-ai/cache/summary?account_id=${encodeURIComponent(accountId!)}`,
      ),
    // eslint-disable-next-line local/no-fixed-polling -- stops when the job ends
    refetchInterval: (q) => (q.state.data?.running ? 1500 : false),
    staleTime: 10_000,
  });
}

export async function startCollect(accountId: string): Promise<{ run_id: number }> {
  return relay.post<{ run_id: number }>(
    `/admin/vault-ai/collect?account_id=${encodeURIComponent(accountId)}`,
    undefined,
    { accountId },
  );
}

export async function fetchCollectStatus(accountId: string): Promise<{ run: CollectRun | null }> {
  return relay.get<{ run: CollectRun | null }>(
    `/admin/vault-ai/collect/status?account_id=${encodeURIComponent(accountId)}`,
  );
}

export interface MirrorItemsOpts {
  accountId: string | null;
  type?: string;
  query?: string;
  sort?: "newest" | "oldest";
  internalFolderId?: number | null;
  /** OF/Fansly folder id — FanId, since Fansly albums are snowflakes >2^53. */
  ofFolderId?: FanId | null;
  /** The grid's picked tag chips (AND). */
  tags?: readonly string[];
  enabled?: boolean;
}

interface MirrorResp {
  list: VaultMedia[];
  hasMore: boolean;
  source: string;
}

/** The cache root for this model's mirror listing. The real keys append the
 *  (type, sort, query, folder) view; this prefix matches all of them. */
export function mirrorItemsKey(accountId: string | null) {
  return ["vault-mirror-items", accountId] as const;
}

/** The one key, pager and fetcher for a mirror listing view: useMirrorItems'
 *  and a background Vault warm both take them from here. */
export function mirrorItemsQuery(opts: Omit<MirrorItemsOpts, "enabled">) {
  const {
    accountId, type = "all", query = "", sort = "newest",
    internalFolderId = null, ofFolderId = null, tags = NO_TAGS,
  } = opts;
  const q = query.trim();
  return infiniteQueryOptions({
    queryKey: [...mirrorItemsKey(accountId), type, sort, q, internalFolderId, ofFolderId, tags.join("\n")],
    initialPageParam: 0,
    getNextPageParam: (last: MirrorResp, all: MirrorResp[]) => (last.hasMore ? all.length * PAGE : undefined),
    queryFn: async ({ pageParam }) => {
      const p = new URLSearchParams();
      p.set("account_id", accountId!);
      p.set("type", type);
      p.set("sort", sort);
      p.set("limit", String(PAGE));
      p.set("offset", String(pageParam ?? 0));
      if (q) p.set("query", q);
      if (internalFolderId != null) p.set("internal_folder_id", String(internalFolderId));
      if (ofFolderId != null) p.set("of_folder_id", String(ofFolderId));
      for (const t of tags) p.append("tags", t);
      return relay.get<MirrorResp>(`/admin/vault-ai/items?${p.toString()}`);
    },
    staleTime: 30_000,
  });
}

const NO_TAGS: readonly string[] = [];

// ── Tag chips ─────────────────────────────────────────────────────

export interface TagFacets {
  /** The busiest tags over the grid's view (type, search, folder, picked chips), each with its item count. */
  tags: { tag: string; count: number }[];
  /** Items matching the whole view: what "Save as folder" would hold. */
  total: number;
  selected: string[];
}

/** GET /admin/vault-ai/tag-facets for the grid's view. Under `mirrorItemsKey`, so every grid invalidation
 *  (an edit, a describe sweep, a refresh) refreshes the chips too. */
export function useTagFacets(opts: {
  accountId: string | null; type: string; query: string; ofFolderId: FanId | null; tags: readonly string[];
  enabled: boolean;
}) {
  const { accountId, type, ofFolderId, tags, enabled } = opts;
  const q = opts.query.trim();
  return useQuery({
    queryKey: [...mirrorItemsKey(accountId), "tag-facets", type, q, ofFolderId, tags.join("\n")],
    queryFn: () => {
      const p = new URLSearchParams({ account_id: accountId!, type });
      if (q) p.set("query", q);
      if (ofFolderId != null) p.set("of_folder_id", String(ofFolderId));
      for (const t of tags) p.append("tags", t);
      return relay.get<TagFacets>(`/admin/vault-ai/tag-facets?${p.toString()}`);
    },
    enabled: enabled && !!accountId,
    staleTime: 30_000,
    // A chip tap keeps the old row on screen while the new counts load (no flash of an empty row).
    placeholderData: (prev) => prev,
  });
}

export interface TagFolderResult {
  folder_id: number;
  name: string;
  tags: string[];
  items: number;
}

/** "Save as folder": an internal folder (created_by operator) holding what the chips' view shows, resolved by
 *  the relay from the same filters. Body from `tagFolderForm.buildPayload`. */
export async function saveTagFolder(body: TagFolderPayload) {
  return relay.post<TagFolderResult>(`/admin/vault-ai/folders/from-tags`, body, { accountId: body.account_id });
}

/** Paginated read of the LOCAL mirror. Same surface as useVaultMedia so the
 *  panel can swap between "Local (fast)" and "Live (OF)" transparently. */
export function useMirrorItems(opts: MirrorItemsOpts) {
  const { accountId, enabled = true } = opts;
  const inf = useInfiniteQuery({
    ...mirrorItemsQuery(opts),
    enabled: enabled && !!accountId,
  });
  const items: VaultMedia[] = (inf.data?.pages ?? []).flatMap((p) => p.list ?? []);
  return {
    items,
    hasMore: !!inf.hasNextPage,
    isLoading: inf.isLoading,
    isFetching: inf.isFetching,
    // Distinct from isFetching: a background refetch of page 1 (invalidate,
    // stale-revalidate) also flips isFetching, and gating "load more" on that
    // silently swallows the scroll trigger. Only a real next-page fetch blocks.
    isFetchingNextPage: inf.isFetchingNextPage,
    error: inf.error,
    loadMore: () => {
      if (inf.hasNextPage && !inf.isFetchingNextPage) inf.fetchNextPage();
    },
    refetch: () => inf.refetch(),
  };
}

// ── Duplicate detection ───────────────────────────────────────────
//
// Re-uploads are ~30% of a mature vault. `original` is the earliest-uploaded
// copy and is always KEPT; `dupes` are the removal candidates. Hiding calls
// OF's own "Remove from vault" (PUT /vault/media/hidden) — the copies leave
// her real vault but are not destroyed, so sent PPVs keep working. OF has no
// unhide, which is why the UI confirms first.

export interface DupeMember {
  media_id: number;
  kind: string;
  created_at: string | null;
  duration_seconds: number | null;
  send_count: number;
  dhash_dist?: number;
  ahash_dist?: number;
  exact?: boolean;
  band?: string;
}

export interface DupeCluster {
  original: DupeMember;
  dupes: DupeMember[];
  band: string;
  worst: number;
  all_exact: boolean;
  sent_dupes: number;
}

export interface DupeScan {
  account_id: string;
  threshold: number;
  scanned: number;
  unhashed: number;
  sets: number;
  removable: number;
  returned: number;
  clusters: DupeCluster[];
  /** Picture items with no cached thumb yet — not hashed, so not in any set. */
  missing_thumbs?: number;
  /** The background thumb fetch the scan kicked off for them (null: none yet). */
  backfill?: { total: number; done: number; failed: number; running: boolean } | null;
}

/** Scan for duplicate sets. Read-only — nothing is hidden by this call. */
export function useDuplicates(accountId: string | null, threshold = 2, enabled = false) {
  return useQuery<DupeScan>({
    queryKey: ["vault-duplicates", accountId, threshold],
    enabled: !!accountId && enabled,
    queryFn: () =>
      relay.get(
        `/admin/vault-ai/duplicates?account_id=${encodeURIComponent(accountId!)}` +
          `&threshold=${threshold}`,
      ),
    staleTime: 60_000,
    // Thumbs for never-rendered items are being fetched: re-scan so the sets grow.
    refetchInterval: (q) => (q.state.data?.backfill?.running ? 8_000 : false),
  });
}

export interface HideDupesResult {
  hidden: number;
  hidden_ids: number[];
  refused: Record<string, number[]>;
  of_error?: string;
  not_hidden?: number[];
}

// The relay caps one request at 500 (blast-radius guard) and a mature vault
// yields ~700 copies, so the selection is sent in batches. Sequential, not
// parallel: these are real writes against her OF account.
const HIDE_BATCH = 250;

/** Remove confirmed copies from the REAL OF vault. The relay re-clusters and
 *  refuses anything that is an original / not a duplicate / already sent.
 *  Batches transparently and aggregates; `onProgress` reports ids completed.
 *  Stops early if a batch reports a partial OF failure, or fails outright
 *  after an earlier one went through (`of_error` = its error, `not_hidden` =
 *  the rest: the earlier batches ARE gone from OF), so the caller can re-offer
 *  the remainder rather than pushing on blindly. A first batch that fails
 *  throws. */
export async function hideDuplicates(
  accountId: string,
  mediaIds: readonly number[],
  opts: {
    threshold?: number;
    allowSent?: boolean;
    onProgress?: (done: number, total: number) => void;
  } = {},
): Promise<HideDupesResult> {
  const agg: HideDupesResult = { hidden: 0, hidden_ids: [], refused: {} };
  for (let i = 0; i < mediaIds.length; i += HIDE_BATCH) {
    const batch = mediaIds.slice(i, i + HIDE_BATCH);
    let res: HideDupesResult;
    try {
      res = await relay.post(
        `/admin/vault-ai/duplicates/hide`,
        {
          account_id: accountId,
          media_ids: batch,
          threshold: opts.threshold ?? 2,
          allow_sent: !!opts.allowSent,
        },
        { accountId },
      );
    } catch (e) {
      if (i === 0) throw e;
      // A later batch that fails stops as one OF half refused does (below): none of it hidden.
      res = { hidden: 0, hidden_ids: [], refused: {}, of_error: errText(e), not_hidden: batch };
    }
    agg.hidden += res.hidden ?? 0;
    agg.hidden_ids.push(...(res.hidden_ids ?? []));
    for (const [why, ids] of Object.entries(res.refused ?? {})) {
      agg.refused[why] = [...(agg.refused[why] ?? []), ...ids];
    }
    // A batch that stopped counts only what it hid.
    opts.onProgress?.(res.of_error ? i + (res.hidden ?? 0) : Math.min(i + batch.length, mediaIds.length), mediaIds.length);
    if (res.of_error) {
      agg.of_error = res.of_error;
      agg.not_hidden = [...(res.not_hidden ?? []), ...mediaIds.slice(i + batch.length)];
      break;
    }
  }
  return agg;
}

/**
 * Every cache root that answers "what is in this model's vault" — the list an
 * import, a bulk move or a delete should invalidate.
 *
 * BUILT from the key factories above and in `useVaultMedia`, not written out as
 * five string literals. The literal version drifted on the day it was added:
 * the panel's `refreshAll` was the same concept hand-written as four keys,
 * missing `vault-of-folders-mirror`, so after an import the folder counts
 * refreshed and after an add-to-folder they did not. Two lists, one concept,
 * disagreeing immediately — and nothing could have caught it, because neither
 * list had any connection to the keys the hooks actually use. Derived, a rename
 * is a type error rather than a silent miss.
 *
 * SCOPE, because the sentence above is easy to over-read: it holds for these
 * five roots, for the queries the hooks here and in `useVaultMedia` issue, and
 * for `VaultManagePanel`, which asks these factories for the ten invalidations
 * it used to hand-write. It does NOT hold for the rest of the app — the vault
 * modals, `chat/VaultPicker`, `ChatList`, `/inbox` and `employees/EmployeeAccess`
 * still spell their keys out, so renaming the string inside `mirrorItemsKey`
 * type-checks and orphans theirs. Repointing them is a separate diff; until it
 * happens, a rename here means grepping for the literal too.
 *
 * Each entry is a `[name, accountId]` PREFIX. TanStack matches key prefixes by
 * element equality, so this covers every (type, folder, sort, search) variant of
 * that model's queries and nothing belonging to another model. It is also why
 * the prefix has to come from the hook: an invalidation of `["vault"]` looks
 * like it covers `["vault-media", …]` and covers nothing at all, which is
 * exactly what the importer used to do against a three-day-old cache.
 */
export function vaultGridKeys(accountId: string | null): readonly (readonly unknown[])[] {
  return [
    vaultMediaKey(accountId),        // live OF listing
    vaultListsKey(accountId),        // OF folders (the rail, the import picker)
    mirrorItemsKey(accountId),       // the local mirror the grid prefers
    cacheSummaryKey(accountId),      // "N cached", and the flag that CHOOSES the mirror
    ofFoldersMirrorKey(accountId),   // mirror-derived folder counts
  ];
}

/** Invalidate all of them. One call, so a caller cannot refresh four of five.
 *
 *  Then the query snapshot (rqPersister) is saved now, not on its throttle: a reload right after a vault write
 *  restores this cache (any edit made before the call, the lists marked stale), not the one from before the write.
 *  Resolves once the mounted ones refetched; callers that only mark stale may drop it. */
export function invalidateVaultGrid(qc: QueryClient, accountId: string | null): Promise<void> {
  const refetched = vaultGridKeys(accountId).map((queryKey) => invalidateVaultQueries(qc, { queryKey }));
  flushPersistedCache();
  return Promise.all(refetched).then(() => undefined);
}
