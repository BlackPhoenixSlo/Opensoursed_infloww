"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { FolderPriceModal } from "@/components/vault/VaultFolderRail";
import { formatPrice } from "@/components/vault/folderPriceForm";
import { setFolderPrice, useFolderPrices } from "@/hooks/useFolderPrices";
import type { StandardFolder } from "@/hooks/useStandardFolders";

export default function VaultStandardFolders({ accountId, folders, selectedId, pending, syncing,
  error, onSelect, onRefresh, mobile = false }: {
  accountId: string; folders: StandardFolder[]; selectedId: number | null;
  pending: number; syncing: boolean; error: boolean;
  onSelect: (folder: StandardFolder | null) => void; onRefresh: () => void; mobile?: boolean;
}) {
  const [pricing, setPricing] = useState<StandardFolder | null>(null);
  const qc = useQueryClient();
  const prices = useFolderPrices(accountId).data;
  const price = (folder: StandardFolder) => prices?.[`vf:${folder.id}`] ?? null;
  const priceButton = (folder: StandardFolder) => folder.priceable && prices !== undefined && (
    <button type="button" aria-label={`Set price for ${folder.kind === "photo" ? "Photos" : "Videos"} / ${folder.name}`}
      className="shrink-0 rounded px-2 py-1 text-xs text-accent hover:bg-accent/10"
      onClick={() => setPricing(folder)}>
      {price(folder) == null ? "Set price" : formatPrice(price(folder)!)}
    </button>
  );
  const selected = folders.find((folder) => folder.id === selectedId);
  return <div className="border-b border-border px-2 py-2" aria-label="Standard categories">
    {mobile ? <div className="flex items-center gap-1">
      <select aria-label="Standard category" className="min-w-0 flex-1 rounded bg-bg p-2 text-sm"
        value={selectedId ?? ""} onChange={(e) => onSelect(folders.find((f) => f.id === Number(e.target.value)) ?? null)}>
        <option value="">Choose a standard category</option>
        {(["photo", "video"] as const).map((kind) => <optgroup key={kind} label={kind === "photo" ? "Photos" : "Videos"}>
          {folders.filter((f) => f.kind === kind).map((f) => <option key={f.id} value={f.id}>{f.name} ({f.items})</option>)}
        </optgroup>)}
      </select>
      {selected && priceButton(selected)}
    </div> : <>
      <p className="px-2 pb-2 text-xs text-fg-dim">Standard categories</p>
      {(["photo", "video"] as const).map((kind) => <details key={kind} open className="mb-1">
        <summary className="cursor-pointer rounded px-2 py-2 text-sm font-semibold">{kind === "photo" ? "Photos" : "Videos"}</summary>
        {folders.filter((f) => f.kind === kind).map((f) => <div key={f.id}
          className={`flex items-center rounded ${selectedId === f.id ? "bg-accent/15" : "hover:bg-fg/5"}`}>
          <button type="button" aria-label={`Open ${kind === "photo" ? "Photos" : "Videos"} / ${f.name}`} aria-pressed={selectedId === f.id} className="min-w-0 flex-1 px-2 py-2 text-left text-sm"
            onClick={() => onSelect(f)}>
            <span className="block break-words">{f.name}</span>
            <span className="text-xs text-fg-dim">{f.items} {kind === "photo" ? "photos" : "videos"}</span>
          </button>
          {priceButton(f)}
        </div>)}
      </details>)}
    </>}
    {pending > 0 && <p className="px-2 pt-1 text-xs text-fg-dim">{pending} awaiting description. Use Describe All to sort them.</p>}
    {syncing && <p role="status" className="px-2 pt-1 text-xs text-fg-dim">Sorting saved descriptions…</p>}
    {error && <p role="alert" className="px-2 pt-1 text-xs text-err">Couldn&apos;t update categories. <button onClick={onRefresh} className="underline">Retry</button></p>}
    {pricing && <FolderPriceModal name={`${pricing.kind === "photo" ? "Photos" : "Videos"} / ${pricing.name}`}
      priceRef={`vf:${pricing.id}`} current={price(pricing)} onCancel={() => setPricing(null)}
      onSave={async (body) => { await setFolderPrice(qc, body); setPricing(null); }} />}
  </div>;
}
