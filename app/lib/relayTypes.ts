import type { Freshness } from "@/lib/creatorFreshness";
import type { FanId } from "@/lib/fanId";


export interface Employee {
  id: number;
  display_name: string;
  color: string | null;
  is_active: boolean;
  chatter_id?: string | null;
  kind?: "owner" | "login" | "name";
  user_id?: string | null;
  username?: string | null;
  created_at?: string | null;
  account_ids?: string[] | null;
  group_id?: number | null;
  last_login_at?: string | null;
  two_factor?: boolean;
}

export interface AccountMeta {
  id: string;
  nickname?: string | null;
  /** The creator's own display name on the platform (distinct from the
   *  team-set `nickname`). Filled by the setup flow from a live me(). */
  name?: string | null;
  /** Which platform the account lives on; read it through lib/platform's `accountPlatform`. */
  platform?: string | null;
  color?: string | null;
  created_at?: string | null;
  last_used_at?: string | null;
  has_session?: boolean;
  // Set while the OF session is flagged dead: every automation is paused until re-captured; absent/null = healthy.
  session_dead_at?: string | null;
  session_dead_reason?: string | null;
  is_active: boolean;
  proxy_down: boolean;
  /** With `proxy_down`: "down" (unreachable) or "flapping" (refusing too many calls: the
   *  PROXY_FLAP_BAD_PCT knob, on by default; 0 = off). */
  proxy_bad_reason?: "down" | "flapping";
  /** "watcher" on a watcher account (GET /admin/accounts' `watchers`, a chatter's roster row): a fan account that
   *  reads what the Creators send, no Creator. Absent on a Creator. */
  role?: "watcher";
  /** The Shared refresher's snapshot of this Creator (lib/creatorFreshness), with its Knob on; absent off. */
  freshness?: Freshness;
}

export type WatcherAccount = AccountMeta & { role: "watcher" };

export interface ProxyHealth {
  state: "healthy" | "suspect" | "bad" | "rechecking";
  errors: number;
  last_error?: string | null;
  last_error_at?: number | null;
  bad_since?: number | null;
  next_recheck_at?: number | null;
  probe?: { ok?: boolean; ttfb_ms?: number | null; error?: string | null };
  trace?: { ip?: string | null; geo?: string | null; colo?: string | null };
  bad_reason?: "down" | "flapping";
  refusals?: { window_s: number; pct: number; refused?: number; calls?: number };
  inflight?: number;
  inflight_peak?: number;
}

export interface ProxyMeta {
  label: string;
  scheme: string;
  host: string;
  port: number;
  username?: string | null;
  password?: string | null;
  notes?: string;
  verified_ip?: string | null;
  verified_at?: string | null;
  health?: ProxyHealth;
  // Many accounts may share one proxy; the UI warns on >1 because OF correlates same-IP behaviour.
  assigned_account_ids?: string[];
  assigned_accounts?: Array<{ id: string; nickname?: string | null; color?: string | null }>;
  assigned_account_id?: string | null;
  assigned_account?: { id: string; nickname?: string | null } | null;
}

export interface LiveRev {
  live_rev: string | null;
  live_fetched_at?: number | null;
}

export interface BootstrapResponse {
  ok: true;
  session_file: string;
  account_id: string;
  user_id: string;
  x_of_rev: string;
}

export interface FanslySessionResponse {
  ok: true;
  account_id: string;
  platform: "fansly";
  name: string | null;
}


export interface OFMediaVariant {
  url: string;
  duration?: number | null;
}
export interface OFMediaFiles {
  thumb?: OFMediaVariant | null;
  squarePreview?: OFMediaVariant | null;
  preview?: OFMediaVariant | null;
  full?: OFMediaVariant | null;
  source?: OFMediaVariant | null;
}
export interface OFMedia {
  id: number | string;
  type?: string;
  url?: string | null;
  files?: OFMediaFiles | null;
  duration?: number | null;
  hasError?: boolean;
  canView?: boolean | null;
  width?: number | null;
  height?: number | null;
}


export interface OFUserMini {
  id: number | string;
  name?: string;
  username?: string;
  avatar?: string | null;
  customNickname?: string | null;
  displayName?: string | null;
  notice?: string | null;
  isRestricted?: boolean;
  badgeExcluded?: boolean;
  isBlocked?: boolean;
  needsHuman?: boolean;
  autoRenewOff?: boolean;
  isVerified?: boolean;
}

// Absent from the captured session bundles (only the sender half is), so grepping the repo won't find `partnerSource`.
export interface MessageReleaseForm {
  id: number;
  name?: string;
  type?: string;
  partnerSource?: string;
}

export interface OFMessage {
  id: number | string;
  text: string;
  fromUser: OFUserMini;
  toUser?: OFUserMini;
  createdAt: string;
  changedAt?: string;
  isFree?: boolean;
  isOpened?: boolean;
  isPaid?: boolean;
  isLiked?: boolean;
  isPinned?: boolean;
  replyToMessageId?: number | string;
  replyToMessage?: {
    id: number | string;
    text?: string;
    fromUser?: OFUserMini;
    createdAt?: string;
    mediaCount?: number;
  } | null;
  price?: number;
  isTip?: boolean;
  lockedText?: boolean;
  media: OFMedia[];
  mediaCount?: number;
  previews?: number[];
  giphyId?: string;
  // Only place a landed tag shows: OF drops tags sent in `userTags` on this endpoint, leaving this empty.
  releaseForms?: MessageReleaseForm[];
  isFromQueue?: boolean;
  canUnsendQueue?: boolean;
  _pending?: boolean;
  _uploading?: boolean;
  _failed?: boolean;
  _failedReason?: string;
  _failedMediaIds?: number[];
  _tempId?: number;
  _isFutureScheduled?: boolean;
  _fireAt?: string;
  _scheduleJobId?: number;
}

export interface OFChatItem {
  id?: number;
  // Fansly fan ids are STRING snowflakes; Number() rounds a real id into a ghost (see fanIdFromParam).
  withUser: OFUserMini & { id: number | string };
  lastMessage?: {
    id: number;
    text?: string;
    fromUser?: OFUserMini;
    createdAt?: string;
    mediaCount?: number;
    isFree?: boolean;
    price?: number;
    isTip?: boolean;
    lockedText?: boolean;
    isOpened?: boolean;
  };
  hasUnread?: boolean;
  unreadMessagesCount?: number;
  lastReadMessageId?: number;
  isOnline?: boolean;
  // When false, the standard send endpoint returns 400; canNotSendReason is OF's reason.
  canSendMessage?: boolean;
  canNotSendReason?: string | null;
  isMutedNotifications?: boolean;
  canGoToProfile?: boolean;
  hasUnreadTips?: boolean;
  countPinnedMessages?: number;
  __accountId?: string;
}

export interface OFChatsResp {
  list?: OFChatItem[];
  chats?: OFChatItem[];
  hasMore: boolean;
}

export interface OFMessagesResp {
  list: OFMessage[];
  hasMore: boolean;
}

export interface AuditAction {
  id: number;
  employee_id: number | null;
  account_id: string | null;
  action: string;
  label: string | null;
  target_type: string | null;
  target_id: string | null;
  payload: unknown;
  at: string | null;
  via?: string | null;
}

export const SALARY_FREQUENCIES = [
  { value: "weekly", label: "Weekly" },
  { value: "biweekly", label: "Bi-weekly" },
  { value: "monthly", label: "Monthly" },
] as const;
export type SalaryFrequency = (typeof SALARY_FREQUENCIES)[number]["value"];

export interface FanRecord {
  account_id: string;
  fan_id: FanId;
  of_username: string | null;
  of_display_name: string | null;
  avatar_url: string | null;
  custom_nickname: string | null;
  generated_nickname: string | null;
  real_name: string | null;
  his_age: string | null;
  home_country: string | null;
  home_city: string | null;
  hobbies: string | null;
  fetishes: string | null;
  self_description: string | null;
  description: string | null;
  notes: string | null;
  tags: string[];
  lifetime_spend_cents: number;
  bought_amount: number;
  subscription_status: string | null;
  subscribed_at: string | null;
  last_message_received_at: string | null;
  source: string;
  is_followed: boolean;
  language: string | null;
  language_source: string | null;
  birthday?: string | null;
  salary?: string | null;
  salary_frequency?: SalaryFrequency | null;
  last_pay_date?: string | null;
  local_timezone?: string | null;
  occupation?: string | null;
  employer?: string | null;
  relationship_status?: string | null;
  relationship_stage?: string | null;
  has_kids?: boolean | null;
  pets?: unknown[];
  persona_age_claimed?: string | null;
  persona_location_claimed?: string | null;
  persona_job_claimed?: string | null;
  persona_claims?: PersonaClaim[];
  persona_claims_resolved?: ResolvedClaim[];
  communication_style?: Record<string, unknown>;
  recent_events_timeline?: { date?: string; event?: string }[];
  profile?: FanProfileBlock;
  created_at: string | null;
  updated_at: string | null;
}

export interface ResolvedClaim {
  label: string;
  value: string;
  column: "persona_age_claimed" | "persona_location_claimed" | "persona_job_claimed" | null;
  at: string | null;
}

export interface PersonaClaim {
  topic?: string;
  claim?: string;
  at?: string;
}

export interface FanProfileBlock {
  rich_note: string;
  short_bio: string | null;
  nickname: string | null;
  q: string[];
  tease: string[];
  last_generated_at: string | null;
}

export interface FanUpdate {
  custom_nickname?: string | null;
  notes?: string | null;
  tags?: string[];
  real_name?: string | null;
  home_country?: string | null;
  home_city?: string | null;
  his_age?: string | null;
  hobbies?: string | null;
  fetishes?: string | null;
  language?: string | null;
  birthday?: string | null;
  salary?: string | null;
  salary_frequency?: SalaryFrequency | null;
  last_pay_date?: string | null;
  persona_age_claimed?: string | null;
  persona_location_claimed?: string | null;
  persona_job_claimed?: string | null;
}

export interface SendMessageBody {
  text: string;
  locked_text?: boolean;
  price?: number;
  media_files?: Array<number | Record<string, unknown>>;
  previews?: number[];
  is_couple_people_media?: boolean;
  is_forward?: boolean;
  reply_to_message_id?: number | string;
  tagged_users?: number[];
  giphy_id?: string;
}


export interface VaultFrameOption { id?: number; url: string; selected?: boolean; custom?: boolean }
export interface VaultFile {
  url?: string;
  width?: number;
  height?: number;
  sources?: unknown[];
  options?: VaultFrameOption[];
}
export interface VaultFiles {
  thumb?: VaultFile | null;
  preview?: VaultFile | null;
  squarePreview?: VaultFile | null;
  full?: VaultFile | null;
  drm?: { manifest?: { hls?: string | null; dash?: string | null } } | null;
}
export interface VaultMedia {
  id: number;
  type: "photo" | "video" | "gif" | "audio" | string;
  isReady?: boolean;
  canView?: boolean;
  hasError?: boolean;
  createdAt?: string;
  duration?: number;
  files?: VaultFiles | null;
  videoSources?: { "720"?: string | null; "240"?: string | null } | null;
  _claim?: Record<string, unknown>;
  _localPreview?: string;
  _uploading?: boolean;
  _thumb?: string;
  /** The /items `_ai` overlay's suggested price (set in /vault), which prices
   *  a chat Composer's Vault pick. Screens reading more of it widen it. */
  _ai?: { suggested_price_cents?: number | null };
}
export interface VaultAiFields {
  description?: string | null;
  video_description?: string | null;
  tags?: string[] | null;
}

export interface VaultMediaResp {
  list: VaultMedia[];
  hasMore: boolean;
}

// Fansly folder ids are STRING snowflakes (>2^53); narrowing to a number lands on a different album.
export interface VaultList {
  id: FanId;
  type: "custom" | "media_stickers" | string;
  name: string;
  hasMedia: boolean;
  videosCount?: number;
  photosCount?: number;
  gifsCount?: number;
  audiosCount?: number;
  medias?: { id?: number | string; type?: string; url?: string | null }[] | null;
}

export type VaultTypeCounts = Pick<VaultList, "photosCount" | "videosCount" | "gifsCount" | "audiosCount">;

export interface VaultListsResp {
  list: VaultList[];
  hasMore?: boolean;
  all?: VaultTypeCounts;
}

export interface OFMessageTemplate {
  id: string;
  template?: string | null;
  text: string;
  displayText?: string;
  price?: number;
  lockedText?: boolean;
  mediaCount?: number;
  media?: Array<{
    id: number;
    type?: string;
    files?: VaultFiles | null;
  }>;
  isActive?: boolean;
  previews?: number[];
}

export interface SavedReply {
  id: number;
  account_id: string;
  title?: string | null;
  text: string;
  price: number;
  locked_text: boolean;
  media: Array<{
    id: number;
    type?: string;
    files?: VaultFiles | null;
  }>;
  tagged_users?: number[];
  previews?: number[];
  gif_id?: string | null;
  gif_url?: string | null;
  script_id?: string | null;
  script_step?: number | null;
  removed_media_ids?: number[];
  tags?: string[];
  notes?: string | null;
  conditional?: string | null;
  sent_count?: number;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface SavedReplySequenceMeta {
  name: string;
  position: number | null;
  created_by: string | null;
  description: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export type FillStatus =
  | "ok" | "already_filled" | "no_paid_steps" | "not_enough_content" | "no_fit" | "price_conflict"
  | "price_out_of_range" | "reserved";

export interface FillOption {
  id: number;
  step: number;
  option: number;
  role: "chat" | "free_media" | "paid_media";
  wants: string | null;
  keep: boolean;
  media: number[];
  previews: number[];
  price_cents: number;
  price_fixed: boolean;
  flags: string[];
}

export type FillConflictRule = "under_min" | "over_max" | "below_earlier" | "quote_unholdable";

export type FillKeptReason = "edited" | "moved" | "missing" | "reserved";

export interface FillPlan {
  status: FillStatus;
  options: FillOption[];
  flags: string[];
  conflict: { step: number; rule: FillConflictRule; price_cents: number } | null;
  describe: {
    described: number;
    target: number;
    remaining: number;
    can_describe: boolean;
    blocked_reason: string | null;
  };
  fingerprint: string;
}

export interface FillUndoEntry {
  id: number;
  media_ids: number[];
  previews: number[];
  price_cents: number;
  price_set: boolean;
}

export interface FillApplyResult {
  status: FillStatus;
  plan: FillPlan;
  applied: FillOption[];
  undo: FillUndoEntry[];
}

export interface FillUndoResult {
  undone: number[];
  kept: Array<{ id: number; reason: FillKeptReason }>;
}

export interface OFScheduledMessage {
  id: number;
  text?: string;
  scheduledDate?: string;
  price?: number;
  lockedText?: boolean;
  mediaCount?: number;
  media?: Array<{
    id: number;
    type?: string;
    files?: VaultFiles | null;
  }>;
  userIds?: number[];
  userLists?: string[];
  groups?: string[];
  __accountId?: string;
}

export interface VaultUploadResp {
  ready: boolean;
  deduped: boolean;
  vault_id: number | null;
  send_with: Array<number | Record<string, unknown>>;
  size?: number;
  filename?: string;
  note?: string;
  existing?: { id?: number; type?: string; files?: VaultFiles | null };
}

export interface TaggedFriendUser {
  id: number;
  name?: string;
  type?: string;
  user?: {
    id: number;
    name?: string;
    username?: string;
    avatar?: string | null;
    avatarThumbs?: { c50?: string; c144?: string } | null;
    isIdentityVerified?: boolean;
  };
}

export interface TaggedFriendUsersResp {
  items: TaggedFriendUser[];
  hasMore: boolean;
}

export interface TaggedCreatorChoice {
  id: number;
  name: string;
  username: string;
  avatar: string | null;
}

export function toChoice(u: TaggedFriendUser): TaggedCreatorChoice {
  const id = u.user?.id ?? u.id;
  const name = u.user?.name ?? u.name ?? u.user?.username ?? `user${id}`;
  return {
    id,
    name,
    username: u.user?.username ?? "",
    avatar:
      u.user?.avatarThumbs?.c50 ||
      u.user?.avatarThumbs?.c144 ||
      u.user?.avatar ||
      null,
  };
}


export interface GiphyImageVariant {
  url?: string;
  mp4?: string;
  webp?: string;
  width?: string;
  height?: string;
}

export interface GiphyImages {
  original?: GiphyImageVariant;
  fixed_height?: GiphyImageVariant;
  fixed_height_small?: GiphyImageVariant;
  fixed_width?: GiphyImageVariant;
  fixed_width_small?: GiphyImageVariant;
  downsized?: GiphyImageVariant;
  preview_gif?: GiphyImageVariant;
  preview_webp?: GiphyImageVariant;
  [k: string]: GiphyImageVariant | undefined;
}

export interface GiphyItem {
  type: "gif";
  id: string;
  url?: string;
  slug?: string;
  title?: string;
  rating?: string;
  images: GiphyImages;
}

export interface GiphyResponse {
  data: GiphyItem[];
  pagination?: { total_count?: number; count?: number; offset?: number };
}
