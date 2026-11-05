"use client";

import { useId, useMemo, useReducer, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Image as ImageIcon, Lock, Plus, Trash2, X } from "lucide-react";

import { fanListsQuery, topRank, type FanList } from "@/components/audience/fanLists";
import { sanitizePriceInput } from "@/lib/priceInput";
import { VaultPicker } from "@/components/chat/VaultPicker";
import { IfButton, IfHelp, IfInput, IfLabel, IfSelect, IfSwitch, IfTextArea } from "@/components/ui/infloww";
import { useVaultLists } from "@/hooks/useVaultMedia";
import { cn } from "@/lib/utils";

import { ImportCaptionsButton } from "./ImportCaptionsButton";
import {
  SYSTEM_AUDIENCES, buildPayload, numStr, payloadToRows, rowsReducer,
  type Kind, type Row,
} from "./premadeRows";
import { fmtPrice } from "@/lib/format";

/** A built-in "frame" when no caller supplies one: the body, then the footer row right-aligned. */
const inlineFrame: PremadeFrame = ({ body, footer }) => (
  <>
    {body}
    <div className="mt-4 flex items-center justify-end gap-2">{footer}</div>
  </>
);

/** Where the form's body and its Reset / Use in rule footer go (ComposeModal puts them in an IfModal).
 *  `dirty`: rows or the repost cycle differ from what the form opened with, so Escape must not drop them. */
export type PremadeFrame = (parts: { body: ReactNode; footer: ReactNode; dirty: boolean }) => ReactNode;

/** The ready-made rule composer: repeating posts / messages, built into the `{posts:[…]}` / `{messages:[…]}`
 *  payload a rule editor stores (`onComposePayload`, "Use in rule"). A rule is single-account
 *  (`forcedAccountId`). */
export function PremadeForm({
  kind,
  forcedAccountId,
  onComposePayload,
  initialPayload,
  frame = inlineFrame,
}: {
  kind: Kind;
  /** The rule's account (vault folders, images, custom lists). */
  forcedAccountId: string;
  /** Receives the built payload ("Use in rule"). */
  onComposePayload: (payload: Record<string, unknown>) => void;
  /** Re-compose mode: seed the rows + repost cycle from a previously saved
   *  `{posts|messages:[…]}` payload so editing an existing rule isn't blank. */
  initialPayload?: Record<string, unknown>;
  frame?: PremadeFrame;
}) {
  const posts = kind === "auto_posts";
  const accountId = forcedAccountId;
  const [rows, dispatch] = useReducer(rowsReducer, undefined, () => payloadToRows(initialPayload, kind));
  // Auto Posts repost CYCLE (list-level, not per-row): re-post the whole list
  // after it finishes. Baked into the auto_posts payload, not the rule cadence.
  const [postsResendAfterHours, setPostsResendAfterHours] = useState(() =>
    posts ? numStr(initialPayload?.resend_after_hours) : "",
  );
  const [postsResendCount, setPostsResendCount] = useState(() =>
    posts ? numStr(initialPayload?.resend_count) : "",
  );
  // What the form opened with: Escape closes only while nothing differs from it.
  const [opened] = useState(() => JSON.stringify([rows, postsResendAfterHours, postsResendCount]));
  const [pickerFor, setPickerFor] = useState<number | null>(null);
  const [previewPickerFor, setPreviewPickerFor] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Custom lists for the mass_premade audience picker (same source + sort as the
  // Mass Online composer). Only fetched for broadcasts.
  // The shared fan-lists cache: every list, not the first page.
  const listsQ = useQuery<FanList[]>({ ...fanListsQuery(accountId), enabled: !!accountId && !posts });
  const customLists = useMemo(() => {
    // OF sometimes tags the built-in "fans"/"following" lists with a type the
    // type-filter misses; drop any whose id already names a system audience so
    // they don't show as redundant custom chips sharing a SYSTEM_AUDIENCES id.
    const systemIds = new Set(SYSTEM_AUDIENCES.map((a) => a.id));
    const filtered = (listsQ.data ?? []).filter(
      (l) =>
        l.type !== "build-in" &&
        l.type !== "built-in" &&
        !systemIds.has(String(l.id)),
    );
    return filtered.slice().sort((a, b) => {
      const an = (a.name ?? "").toLowerCase();
      const bn = (b.name ?? "").toLowerCase();
      const ra = topRank(an);
      const rb = topRank(bn);
      if (ra !== rb) return ra - rb;
      return an.localeCompare(bn);
    });
  }, [listsQ.data]);

  // Vault folders for the per-row folder pool (same hook as AutoStoriesTab).
  // Only folders WITH photos — posts/mass attach photos.
  const foldersQ = useVaultLists(accountId);
  const photoFolders = useMemo(
    () => (foldersQ.data?.list ?? []).filter((f) => (f.photosCount ?? 0) > 0),
    [foldersQ.data],
  );

  // Shorthand for the ~20 per-field inputs below.
  function patchRow(i: number, patch: Partial<Row>) {
    dispatch({ type: "patch", i, patch });
  }
  function reset() {
    dispatch({ type: "reset" });
    setPostsResendAfterHours("");
    setPostsResendCount("");
    setError(null);
  }

  const cycle = { resendCount: postsResendCount, resendAfterHours: postsResendAfterHours };

  /** The payload, minus `dry_run` (that's a separate rule knob in the editor). */
  function useInRule() {
    setError(null);
    const payload = buildPayload(rows, cycle, { kind });
    if (!payload) {
      setError(posts ? "Add at least one post with text or media"
                     : "Add at least one message with text or media");
      return;
    }
    onComposePayload(payload);
  }

  /** A folder-pool select: "None" always clears it, even with no folders fetched; a saved folder that is gone
   *  (deleted or emptied) stays listed so the rule shows it and can drop it. */
  const folderSelect = (id: string, value: string, onChange: (v: string) => void) => (
    <IfSelect
      id={id}
      value={value}
      onChange={onChange}
      disabled={foldersQ.isLoading}
      placeholder="Loading folders…"
      options={foldersQ.isLoading ? [] : [
        { value: "", label: photoFolders.length ? "None" : "No photo folders" },
        ...photoFolders.map((f) => ({ value: String(f.id), label: `${f.name} (${f.photosCount} photos)` })),
        ...(value && !photoFolders.some((f) => String(f.id) === value)
          ? [{ value, label: `Missing folder #${value}` }] : []),
      ]}
      className="w-full"
    />
  );

  const body = (
    <div className="space-y-4">
      {rows.map((r, i) => (
        <section key={i} className="space-y-4 rounded-md border border-border p-4">
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-[14px] font-medium text-fg">{posts ? "Post" : "Message"} {i + 1}</h3>
            {rows.length > 1 && (
              <IfButton variant="link" icon={Trash2} onClick={() => dispatch({ type: "remove", i })}
                className="text-err hover:text-err/80">Remove</IfButton>
            )}
          </div>

          {/* Text variant POOL — a random one is sent each fire. */}
          <div className="space-y-2">
            {r.texts.map((t, ti) => (
              <div key={ti} className="flex items-start gap-2">
                <IfTextArea
                  value={t}
                  onChange={(e) => dispatch({ type: "patchText", i, ti, val: e.target.value })}
                  placeholder={
                    r.texts.length > 1
                      ? `Variant ${ti + 1} (random one sent)`
                      : posts ? "Post caption…" : "Broadcast text…"
                  }
                  rows={2}
                  className="min-w-0 flex-1"
                />
                {r.texts.length > 1 && (
                  <IfButton variant="link" icon={X} title="Remove this variant" aria-label="Remove this variant"
                    onClick={() => dispatch({ type: "removeText", i, ti })}
                    className="text-muted hover:text-err" />
                )}
              </div>
            ))}
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
              <IfButton variant="link" onClick={() => dispatch({ type: "addText", i })}>Add variant</IfButton>
              <ImportCaptionsButton current={r.texts} onImport={(vals) => dispatch({ type: "addTexts", i, vals })} />
            </div>
          </div>

          {/* Image POOL — pre-picked vault media AND/OR a whole vault folder.
           *  Both feed one pool; `media_count` is sampled from it per fire. */}
          <MediaPool
            idPrefix={`pm-${kind}-${i}`}
            folderSelect={(id) => folderSelect(id, r.folderId, (v) => patchRow(i, { folderId: v }))}
            picked={r.media.length}
            pickLabel="Pick image pool"
            pickedLabel={`${r.media.length} in pool`}
            onPick={() => setPickerFor(i)}
            onClear={() => patchRow(i, { media: [] })}
          />
          {/* How many to attach per fire — sampled from the combined pool
           *  (picked images ∪ folder). Shown once either source is set. */}
          {(r.media.length > 0 || r.folderId) && (
            <CountLine
              lead="Send"
              value={r.mediaCount}
              onChange={(v) => patchRow(i, { mediaCount: v })}
              tail={`image${r.mediaCount === "1" ? "" : "s"} at random per fire${
                r.media.length > 0 && r.folderId
                  ? ` (from ${r.media.length} picked + folder)`
                  : r.media.length > 0 ? ` (of ${r.media.length} picked)` : " (from folder)"}`}
            />
          )}

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            {/* PPV price — a priced post/broadcast is paywalled; OF needs at
             *  least one image attached. Blank/0 = free. Both kinds support it
             *  (auto_posts→create_post, mass_premade→send_mass_message). */}
            <Field label="Price (USD)" help={Number(r.price) > 0 && (
              <span className="flex items-center gap-1 text-warn">
                <Lock className="h-3 w-3" aria-hidden />PPV {fmtPrice(Math.round(Number(r.price) * 100))} · needs an image
              </span>
            )}>
              {(id) => (
                <IfInput id={id} inputMode="decimal" value={r.price} placeholder="0 (free)" className="w-full"
                  onChange={(e) => patchRow(i, { price: sanitizePriceInput(e.target.value) })} />
              )}
            </Field>
            {posts ? (
              <NumField label="Auto-delete after" help="hours · blank = keep" placeholder="e.g. 6"
                value={r.hoursToLive} onChange={(v) => patchRow(i, { hoursToLive: v })} />
            ) : (
              <NumField label="Auto-unsend after" help="hours · blank = keep" placeholder="e.g. 8"
                value={r.unsendAfterHours} onChange={(v) => patchRow(i, { unsendAfterHours: v })} />
            )}
            <NumField label={i === 0 ? "Delay before posting" : "Delay after previous"} help="minutes"
              placeholder={i === 0 ? "0 (now)" : "e.g. 30"}
              value={r.delayMinutes} onChange={(v) => patchRow(i, { delayMinutes: v })} />
            {!posts && (
              <>
                <NumField label="Resend this many times" help="0 = once" placeholder="0"
                  value={r.resendCount} onChange={(v) => patchRow(i, { resendCount: v })} />
                <NumField label="Wait between resends" help="hours" placeholder="e.g. 24"
                  value={r.resendAfterHours} onChange={(v) => patchRow(i, { resendAfterHours: v })} />
              </>
            )}
          </div>

          {/* Free-preview pool — PAID auto_posts only. These images post as a
           *  FREE teaser on the paywalled post (the backend adds them to the
           *  attachment set so they're always a valid subset). */}
          {posts && Number(r.price) > 0 && (
            <div className="space-y-4 border-t border-border pt-4">
              <div>
                <h4 className="text-[14px] font-medium text-fg">Free preview pool</h4>
                <IfHelp>Shown unlocked as the teaser.</IfHelp>
              </div>
              <MediaPool
                idPrefix={`pm-${kind}-${i}-preview`}
                folderSelect={(id) => folderSelect(id, r.previewFolderId, (v) => patchRow(i, { previewFolderId: v }))}
                picked={r.previewMedia.length}
                pickLabel="Pick preview pool"
                pickedLabel={`${r.previewMedia.length} in preview pool`}
                onPick={() => setPreviewPickerFor(i)}
                onClear={() => patchRow(i, { previewMedia: [] })}
              />
              {(r.previewMedia.length > 0 || r.previewFolderId) && (
                <CountLine
                  lead="Show"
                  value={r.previewCount}
                  onChange={(v) => patchRow(i, { previewCount: v })}
                  tail={`image${r.previewCount === "1" ? "" : "s"} free per fire`}
                />
              )}
            </div>
          )}

          {!posts && (
            <div className="space-y-4 border-t border-border pt-4">
              <h4 className="text-[14px] font-medium text-fg">Audience</h4>
              <div>
                <IfSwitch label="Only fans online right now" checked={r.onlineOnly}
                  onChange={(on) => patchRow(i, { onlineOnly: on })} />
                <IfHelp>OF resolves it at send time.</IfHelp>
              </div>

              {/* System audiences — tri-state chips (off → include → exclude). */}
              <div className="flex flex-wrap gap-2">
                {SYSTEM_AUDIENCES.map((b) => {
                  const state = r.includes.includes(b.id)
                    ? "in"
                    : r.excludes.includes(b.id) ? "ex" : "off";
                  return (
                    <SysChip
                      key={b.id}
                      state={state}
                      onClick={() => dispatch({ type: "cycleSystem", i, id: b.id })}
                      label={b.label}
                    />
                  );
                })}
              </div>

              {/* Custom lists — include / exclude columns. */}
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div>
                  <IfLabel>Include custom lists</IfLabel>
                  <ListColumn
                    lists={customLists}
                    loading={listsQ.isLoading}
                    selected={new Set(r.includes)}
                    onToggle={(id) => dispatch({ type: "toggleListInclude", i, id })}
                    emptyLabel="No custom lists."
                  />
                </div>
                <div>
                  <IfLabel>Exclude custom lists</IfLabel>
                  <ListColumn
                    lists={customLists}
                    loading={listsQ.isLoading}
                    selected={new Set(r.excludes)}
                    onToggle={(id) => dispatch({ type: "toggleListExclude", i, id })}
                    emptyLabel="No custom lists."
                  />
                </div>
              </div>

              {/* DB-sourced add/exclude knobs (resolved server-side). */}
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <NumField label="Exclude I replied to" help="last N hours" placeholder="e.g. 2"
                  value={r.excludeRepliedHours} onChange={(v) => patchRow(i, { excludeRepliedHours: v })} />
                <NumField label="Exclude who messaged me" help="last N hours" placeholder="e.g. 2"
                  value={r.excludeInboundHours} onChange={(v) => patchRow(i, { excludeInboundHours: v })} />
                <NumField label="Include chatted-with" help="last N hours"
                  value={r.recentChatHours} onChange={(v) => patchRow(i, { recentChatHours: v })} />
                <NumField label="Cap recent-chat to" help="N fans"
                  value={r.recentChatLimit} onChange={(v) => patchRow(i, { recentChatLimit: v })} />
                <NumField label="Include fans with unread" help="up to N"
                  value={r.unreadLimit} onChange={(v) => patchRow(i, { unreadLimit: v })} />
              </div>
            </div>
          )}
        </section>
      ))}

      <div>
        <IfButton icon={Plus} onClick={() => dispatch({ type: "add" })} className="w-full">
          Add another {posts ? "post" : "message"}
        </IfButton>
        <IfHelp>
          {posts
            ? "Each post publishes on its own, in order; one text variant is picked at random each time."
            : "Each message is its own broadcast to its own audience; one text variant is picked at random each time."}
        </IfHelp>
      </div>

      {/* Auto Posts repost cycle — list-level, re-posts the WHOLE list after it finishes. */}
      {posts && (
        <section className="space-y-4 rounded-md border border-border p-4">
          <h3 className="text-[14px] font-medium text-fg">Repost cycle</h3>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <NumField label="Repost whole list after" help="hours · blank = once" placeholder="e.g. 24"
              value={postsResendAfterHours} onChange={setPostsResendAfterHours} />
            <NumField label="Repost this many times" help="0 = once" placeholder="0"
              value={postsResendCount} onChange={setPostsResendCount} />
          </div>
        </section>
      )}

      <VaultPicker
        open={pickerFor !== null}
        onClose={() => setPickerFor(null)}
        accountId={accountId}
        fanId={null}
        initialSelectedIds={pickerFor !== null ? rows[pickerFor].media.map((m) => m.id) : []}
        onConfirm={(picked) => {
          if (pickerFor !== null) patchRow(pickerFor, { media: picked });
          setPickerFor(null);
        }}
      />

      <VaultPicker
        open={previewPickerFor !== null}
        onClose={() => setPreviewPickerFor(null)}
        accountId={accountId}
        fanId={null}
        initialSelectedIds={previewPickerFor !== null ? rows[previewPickerFor].previewMedia.map((m) => m.id) : []}
        onConfirm={(picked) => {
          if (previewPickerFor !== null) patchRow(previewPickerFor, { previewMedia: picked });
          setPreviewPickerFor(null);
        }}
      />
    </div>
  );

  const footer = (
    <>
      {error && <span className="mr-auto min-w-0 text-[12px] text-err">{error}</span>}
      <IfButton onClick={reset}>Reset</IfButton>
      <IfButton variant="primary" onClick={useInRule}>Use in rule</IfButton>
    </>
  );

  const dirty = JSON.stringify([rows, postsResendAfterHours, postsResendCount]) !== opened;
  return <>{frame({ body, footer, dirty })}</>;
}

/** Folder pool + picked-image pool, side by side. */
function MediaPool({ idPrefix, folderSelect, picked, pickLabel, pickedLabel, onPick, onClear }: {
  idPrefix: string;
  folderSelect: (id: string) => ReactNode;
  picked: number;
  pickLabel: string;
  pickedLabel: string;
  onPick: () => void;
  onClear: () => void;
}) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      <div>
        <IfLabel htmlFor={`${idPrefix}-folder`}>Folder pool</IfLabel>
        {folderSelect(`${idPrefix}-folder`)}
      </div>
      <div>
        <IfLabel>Image pool</IfLabel>
        <div className="flex items-center gap-4">
          <IfButton icon={ImageIcon} onClick={onPick}>{picked ? pickedLabel : pickLabel}</IfButton>
          {picked > 0 && <IfButton variant="link" onClick={onClear}>Clear</IfButton>}
        </div>
      </div>
    </div>
  );
}

/** "Send [n] images at random per fire": how many of a pool go out each time. */
function CountLine({ lead, value, onChange, tail }: {
  lead: string;
  value: string;
  onChange: (v: string) => void;
  tail: string;
}) {
  return (
    <label className="flex flex-wrap items-center gap-2 text-fg-dim">
      <span>{lead}</span>
      <IfInput inputMode="numeric" value={value} placeholder="1" className="w-16 text-center"
        onChange={(e) => onChange(e.target.value.replace(/[^0-9]/g, ""))} />
      <span>{tail}</span>
    </label>
  );
}

/** Tri-state chip for system audiences: off / include / exclude. */
function SysChip({
  state, onClick, label,
}: {
  state: "off" | "in" | "ex";
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title="Click to cycle: off → include → exclude → off"
      className={cn(
        "h-7 rounded-full border border-border px-3 text-[14px] transition-colors",
        state === "off" && "text-fg-dim hover:border-accent hover:text-fg",
        state === "in" && "border-accent/40 bg-accent/10 text-accent",
        state === "ex" && "border-err/40 text-err line-through",
      )}
    >
      {state === "in" ? "Include · " : state === "ex" ? "Exclude · " : ""}{label}
    </button>
  );
}

/** A scrollable checkbox column of custom lists (include OR exclude). Mirrors
 *  the Mass Online composer's ListColumn. */
function ListColumn({
  lists, loading, selected, onToggle, emptyLabel,
}: {
  lists: FanList[];
  loading: boolean;
  selected: Set<string>;
  onToggle: (id: string) => void;
  emptyLabel: string;
}) {
  if (loading) return <div className="text-muted">Loading…</div>;
  if (lists.length === 0) {
    return <div className="text-muted">{emptyLabel}</div>;
  }
  return (
    <div className="flex max-h-32 flex-col gap-1 overflow-y-auto pr-1">
      {lists.map((l) => {
        const id = String(l.id);
        return (
          <label key={id} className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 hover:bg-bg-elev-1">
            <input type="checkbox" checked={selected.has(id)} onChange={() => onToggle(id)} className="accent-accent" />
            <span className="flex-1 truncate">{l.name || `List #${id}`}</span>
            <span className="shrink-0 text-[12px] text-muted">{l.usersCount ?? 0}</span>
          </label>
        );
      })}
    </div>
  );
}

/** A labelled field with one help line; `children` gets the input's id. */
function Field({ label, help, children }: {
  label: string;
  help?: ReactNode;
  children: (id: string) => ReactNode;
}) {
  const id = useId();
  return (
    <div className="min-w-0">
      <IfLabel htmlFor={id}>{label}</IfLabel>
      {children(id)}
      {help && <IfHelp>{help}</IfHelp>}
    </div>
  );
}

/** A labelled numeric input — blank = the knob isn't applied. */
function NumField({
  label, help, value, onChange, placeholder,
}: {
  label: string;
  help: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <Field label={label} help={help}>
      {(id) => (
        <IfInput id={id} inputMode="numeric" value={value} placeholder={placeholder} className="w-full"
          onChange={(e) => onChange(e.target.value.replace(/[^0-9.]/g, ""))} />
      )}
    </Field>
  );
}
