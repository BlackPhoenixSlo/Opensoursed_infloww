"use client";

import { useId, useMemo, useState, type ReactNode } from "react";
import { ChevronDown, Image as ImageIcon, Lock } from "lucide-react";

import { ListColumn, SYSTEM_AUDIENCES, useFanLists } from "@/components/audience/fanLists";
import { sanitizePriceInput } from "@/lib/priceInput";
import { VaultPicker } from "@/components/chat/VaultPicker";
import { IfButton, IfHelp, IfInput, IfLabel, IfSegmented, IfSelect } from "@/components/ui/infloww";
import { useVaultLists } from "@/hooks/useVaultMedia";

import {
  hasMoreAudience, lastChatChips,
  type Kind, type Row, type RowsAction,
} from "./premadeRows";
import { VariantsField } from "./VariantsField";
import { fmtPrice } from "@/lib/format";
import { cn } from "@/lib/utils";

/** A ready-made rule's ONE post (Auto Post) or message (Auto Mass), inline in the rule popup (ReadyMadeRuleEditor;
 *  its only clock is the rule's "Run every"). Controlled: the popup's reducer owns `row` (ruleEditorForm), this only
 *  dispatches premadeRows actions. A rule is single-account (`accountId`). */
export function PremadeFields({
  kind,
  accountId,
  row: r,
  dispatch,
}: {
  kind: Kind;
  /** The rule's account (vault folders, images, custom lists). */
  accountId: string;
  row: Row;
  dispatch: (a: RowsAction) => void;
}) {
  const posts = kind === "auto_posts";
  const i = 0; // the one row
  const [listMode, setListMode] = useState<"include" | "exclude">("include");
  // The one vault picker: which pool it fills.
  const [picker, setPicker] = useState<"media" | "previewMedia" | null>(null);
  // Auto Mass "More settings" (the rarely used audience knobs): closed unless the saved message uses one.
  const [moreOpen, setMoreOpen] = useState(() => !posts && hasMoreAudience(r));

  // Custom lists for the mass_premade audience picker (the house fan-lists read, shared cache). Only fetched for
  // broadcasts.
  const { customLists, isLoading: listsLoading } = useFanLists(posts ? null : accountId);

  // Vault folders for the folder pool (same hook as AutoStoriesTab).
  // Only folders WITH photos — posts/mass attach photos.
  const foldersQ = useVaultLists(accountId);
  const photoFolders = useMemo(
    () => (foldersQ.data?.list ?? []).filter((f) => (f.photosCount ?? 0) > 0),
    [foldersQ.data],
  );

  // Shorthand for the ~20 per-field inputs below.
  function patchRow(patch: Partial<Row>) {
    dispatch({ type: "patch", i, patch });
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

  return (
    <div className="space-y-4">
      {/* Text variant POOL — a random one is sent each fire. */}
      <VariantsField
        id={`pm-${kind}-text`}
        label={posts ? "Caption" : "Message"}
        variants={r.texts}
        placeholder={posts ? "Post caption…" : "Broadcast text…"}
        help="One is picked at random each time."
        onChange={(texts) => patchRow({ texts })}
      />

      {/* Image POOL — pre-picked vault media AND/OR a whole vault folder.
       *  Both feed one pool; `media_count` is sampled from it per fire. */}
      <MediaPool
        idPrefix={`pm-${kind}`}
        folderSelect={(id) => folderSelect(id, r.folderId, (v) => patchRow({ folderId: v }))}
        picked={r.media.length}
        pickLabel="Pick image pool"
        pickedLabel={`${r.media.length} in pool`}
        onPick={() => setPicker("media")}
        onClear={() => patchRow({ media: [] })}
      />
      {/* How many to attach per fire — sampled from the combined pool
       *  (picked images ∪ folder). Shown once either source is set. */}
      {(r.media.length > 0 || r.folderId) && (
        <CountLine
          lead="Send"
          value={r.mediaCount}
          onChange={(v) => patchRow({ mediaCount: v })}
          tail={`image${r.mediaCount === "1" ? "" : "s"} at random per fire${
            r.media.length > 0 && r.folderId
              ? ` (from ${r.media.length} picked + folder)`
              : r.media.length > 0 ? ` (of ${r.media.length} picked)` : " (from folder)"}`}
        />
      )}

      <div className="grid grid-cols-2 gap-4">
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
              onChange={(e) => patchRow({ price: sanitizePriceInput(e.target.value) })} />
          )}
        </Field>
        {posts ? (
          <NumField label="Auto-delete after" help="hours · blank = keep" placeholder="e.g. 6"
            value={r.hoursToLive} onChange={(v) => patchRow({ hoursToLive: v })} />
        ) : (
          <NumField label="Auto-unsend after" help="hours · blank = keep" placeholder="e.g. 8"
            value={r.unsendAfterHours} onChange={(v) => patchRow({ unsendAfterHours: v })} />
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
            idPrefix={`pm-${kind}-preview`}
            folderSelect={(id) => folderSelect(id, r.previewFolderId, (v) => patchRow({ previewFolderId: v }))}
            picked={r.previewMedia.length}
            pickLabel="Pick preview pool"
            pickedLabel={`${r.previewMedia.length} in preview pool`}
            onPick={() => setPicker("previewMedia")}
            onClear={() => patchRow({ previewMedia: [] })}
          />
          {(r.previewMedia.length > 0 || r.previewFolderId) && (
            <CountLine
              lead="Show"
              value={r.previewCount}
              onChange={(v) => patchRow({ previewCount: v })}
              tail={`image${r.previewCount === "1" ? "" : "s"} free per fire`}
            />
          )}
        </div>
      )}

      {!posts && (
        <div className="space-y-4 border-t border-border pt-4">
          <h4 className="text-[14px] font-medium text-fg">Audience</h4>
          <div>
            <IfLabel>Send to</IfLabel>
            {/* System audiences are include-only; Send to online only toggles the same online_only payload flag. */}
            <div className="flex flex-wrap gap-2" role="group" aria-label="Send to">
              {SYSTEM_AUDIENCES.map((b) => (
                <AudienceChip
                  key={b.id}
                  active={r.includes.includes(b.id)}
                  onClick={() => dispatch({ type: "toggleListInclude", i, id: b.id })}
                  label={b.label}
                />
              ))}
              <AudienceChip active={r.onlineOnly} label="Send to online only"
                onClick={() => patchRow({ onlineOnly: !r.onlineOnly })} />
            </div>
            <IfHelp>When selected, only users online at send time receive the message.</IfHelp>
          </div>

          {/* One multi-select picker, with Include / Exclude tabs both visible. */}
          <div>
            <div role="tablist" aria-label="Custom lists" className="mb-2 flex gap-2">
              {(["include", "exclude"] as const).map((mode) => {
                const count = mode === "include"
                  ? r.includes.filter((id) => !["fans", "following"].includes(id)).length
                  : r.excludes.length;
                return (
                  <button key={mode} type="button" role="tab" aria-selected={listMode === mode}
                    aria-controls={`pm-${kind}-lists-panel`} onClick={() => setListMode(mode)}
                    className={cn("min-h-9 rounded-md border px-3 text-sm",
                      listMode === mode ? "border-accent bg-accent/10 text-accent" : "border-border text-fg-dim hover:text-fg")}>
                    {mode === "include" ? "Include" : "Exclude"}{count ? ` · ${count}` : ""}
                  </button>
                );
              })}
            </div>
            <div role="tabpanel" id={`pm-${kind}-lists-panel`} aria-label={listMode === "include" ? "Include custom lists" : "Exclude custom lists"}
              className="max-h-40 overflow-y-auto rounded-md border border-border p-2">
              <ListColumn
                lists={customLists}
                loading={listsLoading}
                selected={new Set(listMode === "include"
                  ? r.includes.filter((id) => !["fans", "following"].includes(id))
                  : r.excludes)}
                onToggle={(id) => dispatch({ type: listMode === "include" ? "toggleListInclude" : "toggleListExclude", i, id })}
                emptyLabel="No custom lists."
              />
            </div>
          </div>

          {/* exclude_last_chat_hours: a fan we OR they messaged in the window is skipped (resolved server-side). */}
          <LastChatChips hours={r.excludeLastChatHours}
            onChange={(v) => patchRow({ excludeLastChatHours: v })} />

          {/* The other DB-sourced add/exclude knobs (resolved server-side), rarely used: behind a disclosure. */}
          <div>
            <button type="button" onClick={() => setMoreOpen((o) => !o)} aria-expanded={moreOpen}
              aria-controls={`pm-${kind}-more`}
              className="flex items-center gap-1 text-[14px] font-medium text-fg-dim hover:text-fg">
              More settings
              <ChevronDown className={cn("h-4 w-4 transition-transform", moreOpen && "rotate-180")} aria-hidden />
            </button>
            {moreOpen && (
              <div id={`pm-${kind}-more`} className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
                <NumField label="Exclude I replied to" help="last N hours" placeholder="e.g. 2"
                  value={r.excludeRepliedHours} onChange={(v) => patchRow({ excludeRepliedHours: v })} />
                <NumField label="Exclude who messaged me" help="last N hours" placeholder="e.g. 2"
                  value={r.excludeInboundHours} onChange={(v) => patchRow({ excludeInboundHours: v })} />
                <NumField label="Include chatted-with" help="last N hours"
                  value={r.recentChatHours} onChange={(v) => patchRow({ recentChatHours: v })} />
                <NumField label="Cap recent-chat to" help="N fans"
                  value={r.recentChatLimit} onChange={(v) => patchRow({ recentChatLimit: v })} />
                <NumField label="Include fans with unread" help="up to N"
                  value={r.unreadLimit} onChange={(v) => patchRow({ unreadLimit: v })} />
              </div>
            )}
          </div>
        </div>
      )}

      {/* Mounted only while open: the popup renders these fields inline, so a closed picker costs nothing. */}
      {picker && (
        <VaultPicker
          open
          onClose={() => setPicker(null)}
          accountId={accountId}
          fanId={null}
          initialSelectedIds={r[picker].map((m) => m.id)}
          onConfirm={(picked) => {
            patchRow({ [picker]: picked });
            setPicker(null);
          }}
        />
      )}
    </div>
  );
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

function AudienceChip({ active, label, onClick }: { active: boolean; label: string; onClick: () => void }) {
  return (
    <button type="button" aria-pressed={active} onClick={onClick}
      className={cn("h-8 rounded-full border px-3 text-[13px] transition-colors",
        active ? "border-[#3563ff]/30 bg-[#3563ff]/10 text-[#3563ff]" : "border-border text-fg-dim hover:border-accent hover:text-fg")}>
      {label}
    </button>
  );
}

/** "Skip fans chatted with in last [Off|1h|3h|8h|24h]" — the one recent-chat guard shown up front. */
function LastChatChips({ hours, onChange }: { hours: string; onChange: (v: string) => void }) {
  const { value, options } = lastChatChips(hours);
  return (
    <div>
      <IfLabel>Skip fans chatted with in last</IfLabel>
      <IfSegmented aria-label="Skip fans chatted with in last" value={value} onChange={onChange} options={options}
        className="max-w-full flex-wrap" />
      <IfHelp>Don&apos;t interrupt live chats.</IfHelp>
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
