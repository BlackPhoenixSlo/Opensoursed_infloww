"use client";

import { useEffect, useReducer } from "react";

import { IfButton, IfModal } from "@/components/ui/infloww";
import { categoryIconsPath } from "@/hooks/useVaultCategoryIcons";
import { errText } from "@/lib/errText";
import { relay } from "@/lib/relay";
import { buildPayload, canSubmit, iconFormReducer, INITIAL_ICON_FORM, tooBig } from "@/components/vault/vaultCategoryIconForm";

export default function VaultCategoryIconDialog({
  accountId, category, name, hasIcon, onSaved, onClose,
}: {
  accountId: string; category: string; name: string; hasIcon: boolean;
  onSaved: () => void; onClose: () => void;
}) {
  // See `vaultCategoryIconForm`: the component only dispatches.
  const [form, dispatch] = useReducer(iconFormReducer, INITIAL_ICON_FORM);
  const { preview, x, y, busy, error } = form;

  useEffect(() => {
    if (preview) return () => URL.revokeObjectURL(preview);
  }, [preview]);

  async function submit(reset = false) {
    if (!canSubmit(form, reset)) return;
    const payload = buildPayload(form);
    dispatch({ type: "submit" });
    try {
      const path = categoryIconsPath(accountId, category);
      if (reset) {
        await relay.delete(path, { accountId });
      } else if (payload) {
        const body = new FormData();
        body.append("file", payload.file);
        body.append("x", String(payload.x));
        body.append("y", String(payload.y));
        await relay.uploadForm(path, body, { accountId });
      }
      dispatch({ type: "done" });
      onSaved();
    } catch (e) {
      dispatch({ type: "failed", error: errText(e) });
    }
  }

  return (
    <IfModal title="Folder icon" width={420} onClose={() => { if (!busy) onClose(); }} footer={
      <>
        {hasIcon && <IfButton disabled={busy} onClick={() => void submit(true)}>Use default</IfButton>}
        <IfButton disabled={busy} onClick={onClose}>Cancel</IfButton>
        <IfButton variant="primary" disabled={!canSubmit(form)} onClick={() => void submit()}>
          {busy ? "Saving…" : "Save icon"}
        </IfButton>
      </>
    }>
      <div className="space-y-3">
        <p className="text-sm text-fg">{name}</p>
        <p className="text-sm text-fg-dim">This icon appears for this category across your agency.</p>
        <label className="block space-y-1 text-sm font-medium">
          <span>Choose an image</span>
          <input type="file" accept="image/jpeg,image/png,image/webp" disabled={busy} className="block w-full"
            onChange={(e) => {
              const chosen = e.currentTarget.files?.[0];
              dispatch({ type: "choose", file: chosen,
                preview: chosen && !tooBig(chosen) ? URL.createObjectURL(chosen) : "" });
            }} />
        </label>
        {preview && (
          <div className="space-y-2">
            {/* This local file preview deliberately bypasses image optimization. */}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={preview} alt="Square folder icon crop"
              className="mx-auto size-36 rounded-xl border border-border object-cover"
              style={{ objectPosition: x + "% " + y + "%" }}
              onLoad={() => dispatch({ type: "loaded" })}
              onError={() => dispatch({ type: "loadFailed" })} />
            <label className="flex items-center gap-2 text-sm">
              Left / right <input type="range" className="flex-1" min={0} max={100} value={x}
                onChange={(e) => dispatch({ type: "move", axis: "x", value: e.currentTarget.valueAsNumber })} disabled={busy} />
            </label>
            <label className="flex items-center gap-2 text-sm">
              Up / down <input type="range" className="flex-1" min={0} max={100} value={y}
                onChange={(e) => dispatch({ type: "move", axis: "y", value: e.currentTarget.valueAsNumber })} disabled={busy} />
            </label>
          </div>
        )}
        {error && <p role="alert" className="text-sm text-err">{error}</p>}
      </div>
    </IfModal>
  );
}
