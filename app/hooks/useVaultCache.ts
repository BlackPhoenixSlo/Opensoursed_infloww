"use client";


import {
  infiniteQueryOptions, keepPreviousData, useInfiniteQuery, useQuery, useQueryClient, type QueryClient,
} from "@tanstack/react-query";

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
import { withinMs } from "@/lib/withinMs";

const PAGE = 40;

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
  skipped_unsafe?: number[];
  skipped_videos?: number[];
  synced: number;
  stale_on_of: number[];
}


export interface PackCandidate {
  media_id: number;
  kind: string;
  rung: string | null;
  suggested: string | null;
  tier: number | null;
  score: number;
  jev?: boolean;
  possible?: boolean;
  free_ok?: boolean | null;
  preselect?: boolean;
  unsafe_on_free?: boolean;
  description: string;
}

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

export async function createOfFolder(accountId: string, name: string, mediaIds: FanId[] = []) {
  return relay.post(
    `/admin/vault-ai/of-folders`,
    { account_id: accountId, name, media_ids: mediaIds },
    { accountId },
  );
}

export async function addToOfFolder(accountId: string, listId: FanId, mediaIds: FanId[]) {
  return relay.post(
    `/admin/vault-ai/of-folders/${encodeURIComponent(String(listId))}/add`,
    { account_id: accountId, media_ids: mediaIds },
    { accountId },
  );
}

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

export type PromptVersion = "v1" | "v2";

export function describeAllBody(opts: {
  force?: boolean;
  restage?: boolean;
  promptVersion?: PromptVersion;
  model?: string;
  limit?: number;
}): Record<string, unknown> {
  return {
    force: !!opts.force,
    restage: !!opts.restage,
    prompt_version: opts.promptVersion ?? "v2",
    ...(opts.model ? { model: opts.model } : {}),
    limit: opts.limit && opts.limit >= 1 ? Math.floor(opts.limit) : "all",
  };
}

export interface VisionCapState {
  day: string;
  provider: string;
  cap_millicents: number;
  spent_millicents: number;
  remaining_millicents: number;
  capped: boolean;
  flagged: boolean;
  blocked_reason: string;
}

export function useDescribePlan(accountId: string | null, promptVersion: PromptVersion) {
  return useQuery<{
    total: number;
    undescribed: number;
    restage: number;
    prompt_version: PromptVersion;
    cap?: VisionCapState;
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


export interface AiFolderItem {
  media_id: number;
  kind: string;
  manual_order: number;
  score: number | null;
  tier: string;
  closes: boolean;
  clothing_state: string;
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
  room?: string;
  health?: string[];
  lane?: string;
  solo: boolean;
  solo_of: number | null;
  change: "new" | "keep";
  topic?: string;
  price?: string | null;
}

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
  topics: string[];
  split: boolean;
  shoots_found: number;
  folders: AiFolder[];
  topic_catalogue: AiFolderTopic[];
  jev: { items: number; with_jev: number };
  changes: PlanChanges;
  dupes_collapsed: number[];
  summary: {
    folders: number;
    scripts: number;
    lanes: number;
    solo_cuts: number;
    topics: number;
    unique_media: number;
    memberships: number;
    dupes_collapsed: number;
  };
  solo_coverage: {
    described: number;
    known: number;
    unknown: number;
    solo: number;
    ready: boolean;
  } | null;
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

// Returns once queued: a whole-vault sweep outlasts any proxy socket (waiting showed "Internal Server Error"); poll useVaultFlagsStatus.
export async function runVaultFlags(accountId: string) {
  return relay.post<{ status: string; candidates: number; already: boolean }>(
    `/admin/vault-ai/flags-all`, { account_id: accountId }, { accountId },
  );
}

export function useVaultFlagsStatus(accountId: string | null, enabled: boolean) {
  return useSweepStatus<VaultFlagsStatus>("flags-all", accountId, {
    enabled,
    pollWhileIdle: enabled,
  });
}

export interface FolderPlanOptions {
  keep?: number;
  solo?: boolean;
  topics?: string[];
  split?: boolean;
}

export function useAiFolderPlan(
  accountId: string | null,
  { keep = 2, solo = false, topics = [], split = true }: FolderPlanOptions = {},
  enabled = false,
) {
  const topicsParam = topics.join(",");
  return useQuery<AiFolderPlan>({
    queryKey: ["vault-ai-folder-plan", accountId, keep, solo, topicsParam, split],
    enabled: !!accountId && enabled,
    placeholderData: keepPreviousData,
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
  of_stale?: number;
  skipped_retire?: { folder_id: number; name: string; of_list_id: number | null }[];
  skipped_adopted?: { folder_id: number; name: string; of_list_id: number | null }[];
  created: {
    folder_id: number;
    name: string;
    items: number;
    reused: boolean;
    of_list_id?: number;
    of_error?: string;
    of_stale?: number;
  }[];
}

// Plan options MUST match the preview: the server re-derives the plan and retires folders it no longer makes (no `solo` here deletes every -solo folder). mirrorToOf is the only write to her OF account.
export async function applyAiFolders(
  accountId: string,
  { keep = 2, solo = false, mirrorToOf = false, topics = [], split = true, expectedRetire }:
    FolderPlanOptions & { mirrorToOf?: boolean; expectedRetire: number[] },
): Promise<ApplyAiFoldersResult> {
  return relay.post(
    `/admin/vault-ai/folder-plan/apply`,
    { account_id: accountId, keep, confirm: true, mirror_to_of: mirrorToOf, solo, topics, split,
      expected_retire: expectedRetire },
    { accountId },
  );
}

export interface FlagsReviewItem {
  media_id: number;
  kind: string;
  iffy: string[];
  iffy_why: string[];
  lanes: string[];
  regions: Record<string, string>;
  over: Record<string, string>;
  description: string;
  clothing_state: string;
  explicitness: string;
  codes: string[];
  settled: string[];
  settled_price: number;
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

export async function searchOf(
  accountId: string,
  query: string,
  signal?: AbortSignal,
): Promise<{ ids: number[]; count: number; source: string }> {
  return relay.post(`/admin/vault-ai/search-of`, { account_id: accountId, query }, { accountId }, signal);
}

export const OF_SEARCH_MS = 60_000;

export interface OfSearch {
  searching: boolean;
  failed: boolean;
  retry: () => void;
}

export function useOfSearch(accountId: string | null, query: string, enabled: boolean): OfSearch {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["vault-search-of", accountId, query] as const,
    queryFn: async ({ signal }) => {
      const until = Date.now() + OF_SEARCH_MS;
      const r = await withinMs(OF_SEARCH_MS, signal, (sig) => searchOf(accountId as string, query, sig));
      await withinMs(Math.max(0, until - Date.now()), signal,
                     () => qc.invalidateQueries({ queryKey: mirrorItemsKey(accountId) })).catch(() => {});
      return r;
    },
    enabled: enabled && !!accountId && !!query,
    staleTime: (query) => (query.state.data?.source === "of_partial" ? 0 : 10 * 60 * 1000),
    gcTime: 10 * 60 * 1000,
    retry: false,
    refetchOnWindowFocus: false,
  });
  return { searching: q.isFetching, failed: q.isError && !q.isFetching, retry: () => { void q.refetch(); } };
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
  // Missing => false: a partial mirror must not switch the picker to the DB path.
  complete?: boolean;
  last_run: { id: number; status: string; total_seen: number | null; finished_at: string | null } | null;
}

export interface CollectRun {
  id: number;
  status: string;
  phase: string | null;
  total_seen: number | null;
  upserted: number | null;
  pages_done: number | null;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  running: boolean;
}

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

export async function answerCollect(accountId: string, answer: "continue" | "stop"): Promise<{ status: string }> {
  return relay.post<{ status: string }>(
    `/admin/vault-ai/collect/${answer}?account_id=${encodeURIComponent(accountId)}`,
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
  ofFolderId?: FanId | null;
  tags?: readonly string[];
  enabled?: boolean;
}

interface MirrorResp {
  list: VaultMedia[];
  hasMore: boolean;
  source: string;
}

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


export interface TagFacets {
  tags: { tag: string; count: number }[];
  total: number;
  selected: string[];
}

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
    placeholderData: (prev) => prev,
  });
}

export interface TagFolderResult {
  folder_id: number;
  name: string;
  tags: string[];
  items: number;
}

export async function saveTagFolder(body: TagFolderPayload) {
  return relay.post<TagFolderResult>(`/admin/vault-ai/folders/from-tags`, body, { accountId: body.account_id });
}

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
    isFetchingNextPage: inf.isFetchingNextPage,
    error: inf.error,
    loadMore: () => {
      // Not isFetching: a background refetch of page 1 also flips it and would swallow the scroll trigger.
      if (inf.hasNextPage && !inf.isFetchingNextPage) inf.fetchNextPage();
    },
    refetch: () => inf.refetch(),
  };
}


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
  missing_thumbs?: number;
  backfill?: { total: number; done: number; failed: number; running: boolean } | null;
}

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

// Relay caps one request at 500 (blast-radius guard); batches go sequentially, these are real writes on her OF account.
const HIDE_BATCH = 250;

// Hide = OF "Remove from vault" (PUT /vault/media/hidden): copies leave her vault but sent PPVs keep working; OF has no unhide.
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
      res = { hidden: 0, hidden_ids: [], refused: {}, of_error: errText(e), not_hidden: batch };
    }
    agg.hidden += res.hidden ?? 0;
    agg.hidden_ids.push(...(res.hidden_ids ?? []));
    for (const [why, ids] of Object.entries(res.refused ?? {})) {
      agg.refused[why] = [...(agg.refused[why] ?? []), ...ids];
    }
    opts.onProgress?.(res.of_error ? i + (res.hidden ?? 0) : Math.min(i + batch.length, mediaIds.length), mediaIds.length);
    if (res.of_error) {
      agg.of_error = res.of_error;
      agg.not_hidden = [...(res.not_hidden ?? []), ...mediaIds.slice(i + batch.length)];
      break;
    }
  }
  return agg;
}

// Prefix keys from the hooks' factories: an invalidation of ["vault"] looks like it covers ["vault-media", ...] and matches nothing.
export function vaultGridKeys(accountId: string | null): readonly (readonly unknown[])[] {
  return [
    vaultMediaKey(accountId),
    vaultListsKey(accountId),
    mirrorItemsKey(accountId),
    cacheSummaryKey(accountId),
    ofFoldersMirrorKey(accountId),
  ];
}

export function invalidateVaultGrid(qc: QueryClient, accountId: string | null): Promise<void> {
  const refetched = vaultGridKeys(accountId).map((queryKey) => invalidateVaultQueries(qc, { queryKey }));
  // Persist the query snapshot now, not on its throttle: a reload right after a vault write must not restore the pre-write cache.
  flushPersistedCache();
  return Promise.all(refetched).then(() => undefined);
}
