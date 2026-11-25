"use client";


import { useState } from "react";
import { ArrowLeft, ListFilter, MoreHorizontal, Plus, Search } from "lucide-react";

import { CreatorRail } from "@/components/shell/CreatorRail";
import { EmptyState, IfButton, IfLearn, InflowwPageHeader } from "@/components/ui/infloww";
import { VaultAccountProvider, useVaultAccount } from "@/components/vault/VaultAccount";
import { RAIL_CLASS, RAIL_HEAD_CLASS, RAIL_ICON_BOX, RAIL_ROW_INNER, railRowClass } from "@/components/vault/VaultFolderRail";
import VaultImportCard from "@/components/vault/VaultImportCard";
import { VaultBrowseMemory } from "@/components/vault/VaultBrowseMemory";
import VaultManagePanel, { VAULT_GRID_CLASS, VAULT_PANES_CLASS } from "@/components/vault/VaultManagePanel";
import VaultMediaToolbar from "@/components/vault/VaultMediaToolbar";
import { VaultTour, useVaultTour, type VaultTourStep } from "@/components/vault/VaultTour";
import { EXTRA_LABEL, EXTRAS_OVERFLOW_LABEL } from "@/lib/openinflowwwwExtras";
import { Skeleton } from "@/components/ui/Skeleton";

const LEARN_HREF = "https://help.infloww.com/en/articles/9346888-vault-pro";

const NO_CREATOR = "No model accounts with a live session.";
const LOADING_CREATORS = "Loading model accounts…";

const ADD_MEDIA_TOUR: VaultTourStep[] = [
  {
    target: "[data-tour='vault-add-media']",
    content: "Click “+ Add media” to upload one or more media files to the vault",
  },
];

const UPLOAD_TOUR: VaultTourStep[] = [
  {
    target: "[aria-label='Upload steps'] > li:nth-child(1) h3",
    title: "First, you’ll need to link a fan account",
    content:
      "Easily start uploading content by linking your fan account. Once you link this account, the Vault will automatically upload media files.",
  },
  {
    target: "[aria-label='Upload steps'] > li:nth-child(2) h3",
    title: "Next, choose the media you want to upload",
    content: "You can drag and drop media file(s) here or select them from your computer",
  },
  {
    target: "[aria-label='Upload steps'] > li:nth-child(3) h3",
    title: "Then, add your media details",
    content:
      "Add all necessary information to your media files, like tags, descriptions, and suggested prices. You can also batch-edit your media to make the process faster and more efficient.",
  },
];

function VaultHeader({ onAddMedia, onExtras }: {
  onAddMedia: () => void;
  onExtras?: () => void;
}) {
  const { accountId, account, sessionLost, ready } = useVaultAccount();
  const noCreator = ready ? NO_CREATOR : LOADING_CREATORS;
  return (
    <div className="shrink-0">
      <InflowwPageHeader
        title="Vault Pro"
        className="max-md:h-auto max-md:min-h-12 max-md:flex-wrap max-md:gap-y-2 max-md:px-3 max-md:py-1.5"
        actions={
          <div className="flex items-center gap-6">
            <IfLearn href={LEARN_HREF} className="font-medium" />
            <div className="flex items-center gap-2">
              <IfButton
                size="lg"
                icon={MoreHorizontal}
                aria-label={EXTRAS_OVERFLOW_LABEL}
                title={EXTRAS_OVERFLOW_LABEL}
                aria-haspopup="dialog"
                onClick={onExtras}
                disabled={!onExtras}
                className="w-9 px-0 [&>svg]:h-4 [&>svg]:w-4"
              />
              <IfButton
                variant="primary"
                size="lg"
                icon={Plus}
                data-tour="vault-add-media"
                onClick={onAddMedia}
                disabled={accountId === null}
                title={accountId === null ? noCreator : undefined}
                className="w-[135px]"
              >
                Add media
              </IfButton>
            </div>
          </div>
        }
      />
      {sessionLost && (
        /* Don't re-adopt another account: it would remount the page and lose staged imports and selection. */
        <p className="border-b border-border px-3 py-2 text-xs text-warn sm:px-6" title={EXTRA_LABEL}>
          {account?.nickname || account?.id || "This model"}&apos;s OnlyFans
          session has dropped — nothing on this page can load until it is
          re-captured. Pick another model on the left to keep working.
        </p>
      )}
    </div>
  );
}

const noop = () => {};

function VaultEmptyFrame() {
  return (
    <div className={VAULT_PANES_CLASS}>
      <aside className={RAIL_CLASS}>
        <div className={RAIL_HEAD_CLASS}>
          <span className="flex items-center text-[13px] font-medium text-fg">
            Default
            <span aria-hidden className="ml-2 grid h-6 w-6 place-items-center text-fg-dim">
              <ListFilter size="1em" />
            </span>
          </span>
          <div className="flex items-center">
            <button type="button" aria-label="Search" disabled className={RAIL_ICON_BOX}>
              <Search size={20} aria-hidden />
            </button>
            <button type="button" aria-label="New category" disabled className={RAIL_ICON_BOX}>
              <Plus size={16} aria-hidden />
            </button>
          </div>
        </div>
        <div className={railRowClass(true)}>
          <div className={RAIL_ROW_INNER}>
            <div className="text-sm font-medium">All media</div>
            <div className="text-xs text-muted">empty</div>
          </div>
        </div>
      </aside>
      <section className="relative flex flex-1 min-h-0 min-w-0 flex-col">
        <VaultMediaToolbar
          disabled
          search=""
          onSearch={noop}
          sort="newest"
          onSort={noop}
          type="all"
          onType={noop}
          typeCounts={null}
          loadedCount={0}
          onRefresh={noop}
          onSelectAll={noop}
          selectMode={false}
          onToggleSelect={noop}
        />
        <div className={VAULT_GRID_CLASS}>
          <EmptyState kind="creator" className="py-10" text={<span title={EXTRA_LABEL}>{NO_CREATOR}</span>} />
        </div>
      </section>
    </div>
  );
}

function VaultProBody() {
  const { accountId, account, accounts, ready, setAccountId } = useVaultAccount();
  const options = account && !accounts.some((a) => a.id === account.id) ? [account, ...accounts] : accounts;
  const [adding, setAdding] = useState(false);
  const [extrasOpen, setExtrasOpen] = useState(false);
  const [addTour, closeAddTour] = useVaultTour("batchUploadEntry", accountId !== null && !adding);
  const [uploadTour, closeUploadTour] = useVaultTour("uploadPageStep", accountId !== null && adding);
  return (
    <div className="relative flex flex-col md:h-[calc(100dvh-var(--shell-top,3.5rem))]">
      <VaultHeader
        onAddMedia={() => {
          closeAddTour();
          setAdding(true);
        }}
        onExtras={accountId === null ? undefined : () => setExtrasOpen((o) => !o)}
      />
      {addTour && !adding && <VaultTour steps={ADD_MEDIA_TOUR} variant="coach" placement="left" spotlightClicks onClose={closeAddTour} />}
      {uploadTour && adding && <VaultTour steps={UPLOAD_TOUR} variant="guide" placement="right" onClose={closeUploadTour} />}
      {/* Keyed on the model so a switch REMOUNTS: stale selected media ids from the old model once got written into the new model's folder. Nothing mounts until the model is known (accountId is a plain string below). */}
      <CreatorRail creators={{ accounts: options, value: accountId, onChange: setAccountId }} className="flex min-h-0 flex-col">
        {accountId === null ? (
          ready ? (
            <VaultEmptyFrame />
          ) : (
            <div role="status" aria-label="Loading" className="grid grid-cols-3 md:grid-cols-6 gap-2 px-3 md:px-6 py-4">
              {Array.from({ length: 8 }, (_, i) => <Skeleton key={i} className="aspect-square w-full rounded-md" />)}
            </div>
          )
        ) : (
          <div key={accountId} className="flex-1 min-h-0 flex flex-col">
            <VaultManagePanel extrasOpen={extrasOpen} onCloseExtras={() => setExtrasOpen(false)} />

            {/* Stays mounted while hidden so staged files survive closing it. */}
            <div
              hidden={!adding}
              className="absolute inset-0 z-[1000] flex flex-col bg-bg"
            >
              <div className="shrink-0 px-6 pt-6">
                <button
                  type="button"
                  aria-label="Back"
                  title={`${EXTRA_LABEL}\nThe picked files are kept, so Back does not ask first.`}
                  onClick={() => setAdding(false)}
                  className="flex items-center text-fg-dim hover:text-fg"
                >
                  <ArrowLeft size={20} aria-hidden />
                </button>
              </div>
              <div className="flex-1 min-h-0 overflow-y-auto p-6">
                <VaultImportCard />
              </div>
            </div>
          </div>
        )}
      </CreatorRail>
    </div>
  );
}

export default function VaultProPage() {
  return (
    <VaultAccountProvider>
      {/* Above the per-model key: each model's grid view survives a switch, never the other's. `sort` resets. */}
      <VaultBrowseMemory>
        <VaultProBody />
      </VaultBrowseMemory>
    </VaultAccountProvider>
  );
}
