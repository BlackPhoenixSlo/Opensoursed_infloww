"use client";

import { useEffect, useState } from "react";

import { IfButton, IfModal } from "@/components/ui/infloww";
import { categoryIconsPath } from "@/hooks/useVaultCategoryIcons";
import { errText } from "@/lib/errText";
import { relay } from "@/lib/relay";

export default function VaultCategoryIconDialog({
  accountId, category, name, hasIcon, onSaved, onClose,
}: {
  accountId: string; category: string; name: string; hasIcon: boolean;
  onSaved: () => void; onClose: () => void;
}) {
  const [file, setFile] = useState<File>();
  const [preview, setPreview] = useState("");
  const [x, setX] = useState(50);
  const [y, setY] = useState(50);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (preview) return () => URL.revokeObjectURL(preview);
  }, [preview]);

  async function submit(reset = false) {
    if (busy || (!reset && (!file || !ready))) return;
    setError("");
    setBusy(true);
    try {
      const path = categoryIconsPath(accountId, category);
      if (reset) {
        await relay.delete(path, { accountId });
      } else if (file) {
        const form = new FormData();
        form.append("file", file);
        form.append("x", String(x / 100));
        form.append("y", String(y / 100));
        await relay.uploadForm(path, form, { accountId });
      }
      onSaved();
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <IfModal title="Folder icon" width={420} onClose={() => { if (!busy) onClose(); }} footer={
      <>
        {hasIcon && <IfButton disabled={busy} onClick={() => void submit(true)}>Use default</IfButton>}
        <IfButton disabled={busy} onClick={onClose}>Cancel</IfButton>
        <IfButton variant="primary" disabled={busy || !ready} onClick={() => void submit()}>
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
              setReady(false);
              setError("");
              setPreview("");
              const chosen = e.currentTarget.files?.[0];
              if (chosen && chosen.size > 8 * 1024 * 1024) {
                setError("Choose an image below 8 MB.");
                setFile(undefined);
                return;
              }
              setX(50);
              setY(50);
              setFile(chosen);
              if (chosen) setPreview(URL.createObjectURL(chosen));
            }} />
        </label>
        {preview && (
          <div className="space-y-2">
            {/* This local file preview deliberately bypasses image optimization. */}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={preview} alt="Square folder icon crop"
              className="mx-auto size-36 rounded-xl border border-border object-cover"
              style={{ objectPosition: x + "% " + y + "%" }}
              onLoad={() => setReady(true)}
              onError={() => { setReady(false); setError("Choose a valid JPG, PNG or WebP image."); }} />
            <label className="flex items-center gap-2 text-sm">
              Left / right <input type="range" className="flex-1" min={0} max={100} value={x}
                onChange={(e) => setX(e.currentTarget.valueAsNumber)} disabled={busy} />
            </label>
            <label className="flex items-center gap-2 text-sm">
              Up / down <input type="range" className="flex-1" min={0} max={100} value={y}
                onChange={(e) => setY(e.currentTarget.valueAsNumber)} disabled={busy} />
            </label>
          </div>
        )}
        {error && <p role="alert" className="text-sm text-err">{error}</p>}
      </div>
    </IfModal>
  );
}
