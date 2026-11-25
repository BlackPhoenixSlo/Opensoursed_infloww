"use client";


import { useReducer } from "react";

import { useQueryClient } from "@tanstack/react-query";
import { FolderPlus, Upload, X } from "lucide-react";

import { IfButton, IfModal } from "@/components/ui/infloww";
import {
  INITIAL_TAG_FOLDER_FORM, buildPayload, canSubmit, capText, folderName, publishedText, publishQuestion, savedText,
  tagFolderFormReducer,
} from "@/components/vault/tagFolderForm";
import { invalidateVaultGrid, publishFolderToOf, saveTagFolder, useTagFacets } from "@/hooks/useVaultCache";
import { errText } from "@/lib/errText";
import type { FanId } from "@/lib/fanId";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import { cn } from "@/lib/utils";

const CHIP = "shrink-0 inline-flex items-center gap-1.5 h-8 px-3 rounded-full border text-[13px] leading-none transition-colors";

export default function VaultTagChips({ accountId, enabled, type, query, ofFolderId, tags, onToggle, onClear }: {
  accountId: string;
  enabled: boolean;
  type: string;
  query: string;
  ofFolderId: FanId | null;
  tags: readonly string[];
  onToggle: (tag: string) => void;
  onClear: () => void;
}) {
  const qc = useQueryClient();
  const facets = useTagFacets({ accountId, type, query, ofFolderId, tags, enabled });
  const [form, dispatch] = useReducer(tagFolderFormReducer, INITIAL_TAG_FOLDER_FORM);

  const rows = facets.data?.tags ?? [];
  const { saved, publish } = form;
  if (!enabled || (rows.length === 0 && tags.length === 0 && !saved)) return null;
  const total = facets.data?.total ?? 0;
  // A chip tap shows the previous view's counts until the new ones land: no save on that stale count.
  const counted = facets.isPlaceholderData ? null : total;
  const rest = rows.filter((r) => !tags.includes(r.tag));
  const tooMany = capText(total);

  async function save() {
    if (!canSubmit(form, tags, counted)) return;
    dispatch({ type: "start" });
    try {
      const res = await saveTagFolder(buildPayload(form, { accountId, tags, type, query, ofFolderId }));
      dispatch({ type: "done", folder: { folderId: res.folder_id, name: res.name, items: res.items } });
    } catch (e) {
      dispatch({ type: "failed", text: `Could not save: ${errText(e)}` });
    }
  }

  async function publishNow() {
    if (!saved) return;
    dispatch({ type: "publishStart" });
    try {
      const res = await publishFolderToOf(accountId, saved.folderId);
      dispatch({ type: "publishDone", text: publishedText(res) });
    } catch (e) {
      dispatch({ type: "publishFailed", text: `Publish failed: ${errText(e)}` });
    }
    void invalidateVaultGrid(qc, accountId);
  }

  return (
    <div title={EXTRA_LABEL} className="px-3 md:px-6 pb-3 flex flex-col gap-2 min-w-0">
      <div role="group" aria-label="Tags" className="flex items-center gap-2 min-w-0 overflow-x-auto overscroll-x-contain [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {tags.length > 0 && (
          <button type="button" onClick={onClear} aria-label="Clear tags"
            className={cn(CHIP, "border-border text-fg-dim hover:text-fg px-2.5")}>
            <X size={14} aria-hidden />
          </button>
        )}
        {tags.map((t) => (
          <button key={t} type="button" aria-pressed onClick={() => onToggle(t)}
            className={cn(CHIP, "border-accent bg-accent/10 text-accent")}>
            {t}
            <span className="text-[12px] opacity-80">{total}</span>
          </button>
        ))}
        {rest.map((r) => (
          <button key={r.tag} type="button" aria-pressed={false} onClick={() => onToggle(r.tag)}
            className={cn(CHIP, "border-border text-fg hover:border-fg-dim")}>
            {r.tag}
            <span className="text-[12px] text-fg-dim">{r.count}</span>
          </button>
        ))}
        {tags.length > 0 && !form.open && (
          <IfButton icon={FolderPlus} onClick={() => dispatch({ type: "open" })} disabled={total === 0}
            className="sticky right-0 ml-auto rounded-full bg-bg">
            Save as folder
          </IfButton>
        )}
      </div>

      {form.open && tags.length > 0 && (
        <form
          aria-label="Save as folder"
          onSubmit={(e) => { e.preventDefault(); void save(); }}
          className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-bg-elev-1 p-2"
        >
          <input
            aria-label="Folder name"
            value={folderName(form, tags)}
            onChange={(e) => dispatch({ type: "name", value: e.target.value })}
            maxLength={120}
            className="h-9 flex-1 min-w-[180px] rounded-md border border-border bg-bg px-2.5 text-base md:text-sm outline-none focus:border-accent"
          />
          <div className="flex items-center gap-2 ml-auto">
            <IfButton onClick={() => dispatch({ type: "close" })} disabled={form.saving}>Cancel</IfButton>
            <IfButton type="submit" variant="primary" disabled={!canSubmit(form, tags, counted)}>
              {form.saving ? "Saving…" : counted == null ? "Counting…" : `Save ${total} item${total === 1 ? "" : "s"}`}
            </IfButton>
          </div>
          {(tooMany || form.error) && (
            <div role="alert" className="basis-full text-[12px] text-warn">{form.error ?? tooMany}</div>
          )}
        </form>
      )}

      {saved && (
        <div role="status" aria-label="Saved folder"
          className="flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-lg border border-border bg-bg-elev-1 px-3 py-2 text-[13px] min-w-0">
          <span className="min-w-0 flex-1 break-words text-ok">{savedText(saved)}</span>
          {publish.step === "done" ? (
            <span className="text-ok">{publish.text}</span>
          ) : (
            <IfButton icon={Upload} onClick={() => dispatch({ type: "publishAsk" })}
              disabled={publish.step === "publishing"}>
              {publish.step === "publishing" ? "Publishing…" : "Publish"}
            </IfButton>
          )}
          <button type="button" aria-label="Dismiss" onClick={() => dispatch({ type: "dismiss" })}
            disabled={publish.step === "publishing"}
            className="grid h-7 w-7 place-items-center rounded text-fg-dim hover:text-fg disabled:opacity-50">
            <X size={14} aria-hidden />
          </button>
          {publish.step === "failed" && <div className="basis-full text-[12px] text-warn">{publish.text}</div>}
        </div>
      )}

      {saved && publish.step === "confirm" && (
        <IfModal
          title="Publish to OnlyFans?"
          onClose={() => dispatch({ type: "publishCancel" })}
          footer={<>
            <IfButton onClick={() => dispatch({ type: "publishCancel" })}>Cancel</IfButton>
            <IfButton variant="primary" onClick={() => void publishNow()}>
              {`Publish ${saved.items} item${saved.items === 1 ? "" : "s"}`}
            </IfButton>
          </>}
        >
          {publishQuestion(saved)}
        </IfModal>
      )}
    </div>
  );
}
