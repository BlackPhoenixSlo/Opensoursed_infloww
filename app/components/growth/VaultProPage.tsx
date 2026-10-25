"use client";

/**
 * Growth > Vault Pro, laid out from its Layout capture (`docs/infloww-layouts/growth-vault-pro.md`, ticket 36).
 *
 * The header is the bundle's: Infloww's 48px page header holding "Vault Pro", "Learn" and "Add media" (#3 to #11),
 * plus our one Extras overflow button left of Add media, which opens our own tools (collect, describe, harvest,
 * duplicates, the pack picker, AI folders, disputes and the flags review) in a right drawer. The Creator is picked on
 * the creator column left of the page (`CreatorRail`, as Smart lists'), in place of the bundle's header select (#6).
 * Beside it, flush and filling the page (#15, #16), the existing Vault manage panel holds the folder rail and the
 * grid; with no Creator, a static frame of the same rail and toolbar, disabled, around an empty state. "Add media"
 * reveals the existing import card where the bundle puts its upload card: over the whole page (#78), with a back
 * arrow (#79). The card's contents are Phase 5's and are not touched here.
 *
 * What the page owns is which model everything below is scoped to (`VaultAccountProvider`): the grid, the review
 * queue and the importer must agree on it, see `VaultAccount`.
 */

import { useState } from "react";
import { ArrowLeft, ListFilter, Loader2, MoreHorizontal, Plus, Search } from "lucide-react";

import { CreatorRail } from "@/components/shell/CreatorRail";
import { EmptyState, IfButton, IfLearn, InflowwPageHeader } from "@/components/ui/infloww";
import { VaultAccountProvider, useVaultAccount } from "@/components/vault/VaultAccount";
import { RAIL_CLASS, RAIL_HEAD_CLASS, RAIL_ICON_BOX, RAIL_ROW_INNER, railRowClass } from "@/components/vault/VaultFolderRail";
import VaultImportCard from "@/components/vault/VaultImportCard";
import VaultManagePanel, { VAULT_GRID_CLASS, VAULT_PANES_CLASS } from "@/components/vault/VaultManagePanel";
import VaultMediaToolbar from "@/components/vault/VaultMediaToolbar";
import { VaultTour, useVaultTour, type VaultTourStep } from "@/components/vault/VaultTour";
import { EXTRA_LABEL, EXTRAS_OVERFLOW_LABEL } from "@/lib/openinflowwwwExtras";

/** #7: the bundle's Learn opens this help article (`openExternalUrl`, index.9f50f370.js @13108064). */
const LEARN_HREF = "https://help.infloww.com/en/articles/9346888-vault-pro";

/** Ours, in place of the capture's not-a-creator text (#13), which is about a fan account the registry cannot hold. */
const NO_CREATOR = "No model accounts with a live session.";

/** The Add media tour (#12): the bundle's `batchUploadEntryJoyrideSteps`, spotlit on the button, to its left. */
const ADD_MEDIA_TOUR: VaultTourStep[] = [
  {
    target: "[data-tour='vault-add-media']",
    content: "Click “+ Add media” to upload one or more media files to the vault",
  },
];

/** The upload guide (#118, #119): the bundle's `uploadPageJoyrideSteps$1` and their text (index.9f50f370.js
 *  @12944789 to @12945400), one per step title of the import card, to its right. */
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

/** The capture's header bar (#3 to #11): title, then Learn, our Extras overflow and Add media at the right; a rule
 *  beneath. On a phone the right-hand group wraps under the title. */
function VaultHeader({ onAddMedia, onExtras }: { onAddMedia: () => void; onExtras?: () => void }) {
  const { accountId, account, sessionLost } = useVaultAccount();
  return (
    <div className="shrink-0">
      <InflowwPageHeader
        title="Vault Pro"
        className="max-md:h-auto max-md:min-h-12 max-md:flex-wrap max-md:gap-y-2 max-md:px-3 max-md:py-1.5"
        actions={
          <div className="flex items-center gap-6">
            {/* #7 to #9: the book icon and 14px M1 text, to Infloww's help article. */}
            <IfLearn href={LEARN_HREF} className="font-medium" />
            <div className="flex items-center gap-2">
              {/* Ours (ADR-0003): the one Extras overflow, which opens the tools drawer. */}
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
              {/* #10, #11: antd's primary button, 135px by 36px, a plus before the label. */}
              <IfButton
                variant="primary"
                size="lg"
                icon={Plus}
                data-tour="vault-add-media"
                onClick={onAddMedia}
                disabled={accountId === null}
                title={accountId === null ? NO_CREATOR : undefined}
                className="w-[135px]"
              >
                Add media
              </IfButton>
            </div>
          </div>
        }
      />
      {sessionLost && (
        /* Said, not acted on. This model's OnlyFans session dropped, so she is
           no longer in the pickable list — but quietly re-adopting the first
           account that IS would move the operator to a different creator
           mid-action, remount the whole page under them, and lose the staged
           import files and the grid selection with no message at all. The
           selection stays where it was put; every request below will fail
           until the session is back, and this line is why. */
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

/** The page with no Creator (#13 to #16, the clone's empty frame): the rail's sort row and an empty "All media" row,
 *  the toolbar with every control off, and an empty state where the grid goes. Static: nothing here reads the
 *  relay, and `VaultManagePanel` stays unmounted, as its `accountId` is a string. */
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

/** The page body, inside the provider so it can key its children on the model. */
function VaultProBody() {
  const { accountId, account, accounts, ready, setAccountId } = useVaultAccount();
  // A model whose session dropped leaves `accounts` but stays selected (`sessionLost`); the column still shows her.
  const options = account && !accounts.some((a) => a.id === account.id) ? [account, ...accounts] : accounts;
  const [adding, setAdding] = useState(false);
  const [extrasOpen, setExtrasOpen] = useState(false);
  // The bundle's order: the Add media tour once the page has a Creator to add to, the upload guide the first time
  // the upload card opens. Each shows once (`useVaultTour`); opening the card ends the first, as there.
  const [addTour, closeAddTour] = useVaultTour("batchUploadEntry", accountId !== null && !adding);
  const [uploadTour, closeUploadTour] = useVaultTour("uploadPageStep", accountId !== null && adding);
  return (
    // `relative`: the import card covers this box while it is open (#78). No page padding: the header bar and the
    // rail and grid below it run edge to edge, and from `md` up fill the height under the top bar (#15, #16).
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
      {/* Nothing below mounts until the model is known, and that is a contract,
          not a loading nicety. It makes `accountId` a plain string for the whole
          subtree (`useVaultAccountId`), which is what removes the null branch
          from the components below — and with it the "…" placeholder, the disabled
          Start button, and two hand-written copies of this same empty state.
          It also stops the first paint mounting the entire page under a
          placeholder key and throwing it away one render later.

          `key` = the model, so switching one REMOUNTS both rather than
          re-rendering them with the previous model's state still in hand. The
          panel holds every selection, the open drawer, the folder filter, the
          search box and the drag-reorder buffer; the import card holds staged
          files and folder ids that go to OnlyFans verbatim. Picking a new chip
          used to leave 30 of the OLD model's media ids selected, and the next
          "add to folder" wrote those ids into the NEW model's folder. One
          mechanism for both, because a remount cannot be forgotten the
          next time a piece of state is added — a reset effect can.
          The cost is that `type` and `sort` go back to their defaults on a
          switch; they are preferences, and worth it. */}
      <CreatorRail creators={{ accounts: options, value: accountId, onChange: setAccountId }} className="flex min-h-0 flex-col">
        {accountId === null ? (
          ready ? (
            <VaultEmptyFrame />
          ) : (
            // #13: the bundle's `Spin` while the page loads.
            <div role="status" aria-label="Loading" className="flex justify-center py-10 text-fg-dim">
              <Loader2 size={24} className="animate-spin" aria-hidden />
            </div>
          )
        ) : (
          <div key={accountId} className="flex-1 min-h-0 flex flex-col">
            <VaultManagePanel extrasOpen={extrasOpen} onCloseExtras={() => setExtrasOpen(false)} />

            {/* #78 to #80: the upload card over the whole page, a 20px back arrow, a 24px body that scrolls. The
                card stays mounted while hidden, so files staged in it survive closing it; it is remounted with the
                rest when the model changes. So Back never asks first, as the bundle's does with files picked (#79):
                nothing is lost, and the title says so. */}
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
      <VaultProBody />
    </VaultAccountProvider>
  );
}
