"use client";

/**
 * Growth > Scripts, laid out from its Layout capture (`docs/infloww-layouts/growth-scripts.md`, tickets 35 and 56):
 * the bundle's script manager over our saved replies.
 *
 * - The header (#3 to #17): "Scripts", "Learn" (Not wired: the help article is off-host) and
 *   "Share" (the selected scripts, or all of them, to other Creators), and the More menu behind the bundle shot's
 *   filled accent plus: Add script, Add sequence > Create new, Add tag, Import > From Excel / From other creators;
 *   Use template and Import from tag are Not wired. Import and Share are `ScriptsImportDialogs`. The Creator is
 *   picked on the creator column left of the page (`CreatorRail`, as Smart lists') in place of the bundle's header
 *   select (#6), without its per-Creator script count (`showScriptCount`): the store has no count read (YAGNI).
 * - The toolbar (#18 to #33): the "Tag" and "Sequence" tabs (Tag first, as the bundle opens, #23), the search, and
 *   "Manage scripts", which swaps the tabs for a back arrow and its title and sorts by Recent or Name (#31 to #33).
 * - Tag and Sequence (#53 to #64): a 248px sidebar beside the selected entry's scripts. Tag lists "All scripts",
 *   each tag, then the untagged scripts (the bundle's `UncategorizedCommon` 8888 / 9999 entries, index.9f50f370.js
 *   @13877942); a sequence lists its steps, numbered by step, "2.1" / "2.2" when one step holds several options
 *   (the bundle's `stepIndex`, @14238300). Each tag and sequence row renames and deletes. No tag or sequence (or no
 *   script at all on Tag) shows the bundle's sequence empty panel.
 * - The list (#34 to #50): the select-all box, the "Expand scripts" switch, then one row per script: name (the step
 *   number in a sequence, #38), its tag and sequence chips (#41, three then "+N"), text, media, price, stats (Not
 *   wired), internal notes (#46), then edit, share and delete, which removes the script from the open
 *   tag or sequence instead (#47, #49). A selection opens the bar (#51): Add to tag, and Delete or Remove.
 *
 * Tags, notes and sequences are stored on the saved reply: `tags`, `notes`, and `script_id` + `script_step` (the
 * pair the chat composer's next-step suggestion follows). A tag exists while a script carries it; a new empty tag
 * lives on this page until a script takes it. The list, the editor and their routes are the Templates tab's
 * (`useSavedReplyEditor`); renames, deletes and bulk tagging go through `POST /admin/saved-replies/relabel`.
 */

import { useEffect, useMemo, useReducer, useState, type ComponentProps } from "react";
import { ArrowLeft, BookOpen, List, MinusCircle, Plus, Search, Share2, Trash2, Workflow, X } from "lucide-react";

import { SCRIPT_NAME_MAX, SCRIPT_TAG_MAX, TemplateDraftEditor, extractError } from "@/components/settings/TemplateDraftEditor";
import { useSavedReplyEditor, useScopedAccount } from "@/components/settings/TemplatesTab";
import { CopyScriptsDialog, ExcelImportDialog } from "@/components/growth/ScriptsImportDialogs";
import { NameModal, ScriptEditModal } from "@/components/growth/ScriptModals";
import {
  MoreMenu, NOT_WIRED, ScriptRow, SequenceEmpty, Sidebar, type SidebarItem,
} from "@/components/growth/ScriptsParts";
import { CreatorRail } from "@/components/shell/CreatorRail";
import { EmptyState, IfSelect, InflowwPageHeader } from "@/components/ui/infloww";
import { useActiveAccounts } from "@/hooks/useAccounts";
import { useDeleteSavedReply, useRelabelSavedReplies } from "@/hooks/useSavedReplies";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import { cn } from "@/lib/utils";
import {
  ALL, INITIAL, UNCATEGORIZED, activeEntry, byName, firstGap, kindOf, livePending, nextStep, scriptRows,
  scriptsPageReducer, selectionOf, sequenceDates, sequencesOf, tagCountsOf, type EntryKind, type Modal,
  type NamePrompt,
} from "@/components/growth/scriptsPageState";

/** The Learn and Share boxes (#9, #10): 75px wide, 0 8px padding, 14px weight 500 T1, an 18px icon 4px from the
 *  text, at full ink, as the bundle shot draws them (#d9d9d9 dark). Learn is Not wired (disabled and titled). */
const HEADER_BOX =
  "min-w-[75px] h-6 px-2 flex items-center justify-center text-sm font-medium text-fg disabled:cursor-not-allowed";

export default function ScriptsPage() {
  const accounts = useActiveAccounts();
  const [accountId, setAccountId] = useScopedAccount();
  const {
    draft, setDraft, saveErr, saving,
    replyQ, replies, startNewReply, startEditReply, save,
  } = useSavedReplyEditor(accountId);
  const deleteM = useDeleteSavedReply(accountId);
  const relabelM = useRelabelSavedReplies(accountId);

  // The view, the open tag and sequence, the checked scripts, the page's new tags, the busy scripts and the last
  // error, the open overlay, the search and the sort: `scriptsPageState.ts`.
  const [page, dispatch] = useReducer(scriptsPageReducer, INITIAL);
  const { view, checked, busy, error, modal, search, sort } = page;
  const [expanded, setExpanded] = useState(false);
  const namePrompt = modal?.kind === "name" ? modal.prompt : null;
  const openModal = (m: Modal) => dispatch({ type: "openModal", modal: m });
  const closeModal = () => dispatch({ type: "closeModal" });
  const clearSelection = () => dispatch({ type: "setChecked", ids: [] });
  // Another Creator: nothing of this one's (draft, selection, new tags, open tag or sequence, error, overlay, search)
  // carries over; an answer to what was done on it is dropped while the page shows another (`account`).
  const pickCreator = (id: string) => {
    setAccountId(id);
    setDraft(null);
    dispatch({ type: "reset", account: id });
  };
  // The first Creator, picked by `useScopedAccount` rather than the column: the page's state takes it too.
  useEffect(() => {
    if (accountId !== page.account) dispatch({ type: "reset", account: accountId });
  }, [accountId, page.account]);

  // ── derived: tags and sequences ──
  const pending = useMemo(() => livePending(page.pendingTags, replies), [page.pendingTags, replies]);
  const tagCounts = useMemo(() => tagCountsOf(replies, pending), [replies, pending]);
  const tagNames = useMemo(() => [...tagCounts.keys()].sort(byName), [tagCounts]);
  const sequences = useMemo(() => sequencesOf(replies), [replies]);
  const seqNames = useMemo(() => [...sequences.keys()].sort(byName), [sequences]);
  // The sidebars' order, as drawn: deleting the open entry opens its neighbour in it.
  const tagOrder = useMemo(() => [ALL, ...tagNames, UNCATEGORIZED], [tagNames]);
  const orderOf = (kind: EntryKind) => (kind === "tag" ? tagOrder : seqNames);
  const activeSeq = activeEntry(page.open.sequence, seqNames);
  const activeTag = activeEntry(page.open.tag, tagOrder) ?? ALL;

  // ── the list for the open view ──
  const rows = useMemo(
    () => scriptRows({ view, replies, sequences, activeSeq, activeTag, q: search.q, sort }),
    [view, replies, sequences, activeSeq, activeTag, search.q, sort],
  );

  const inTag = view === "tags" && activeTag !== ALL && activeTag !== UNCATEGORIZED ? activeTag : null;
  const inSeq = view === "sequences" ? activeSeq : null;
  const removeLabel = inTag ? "Remove from tag" : inSeq ? "Remove from sequence" : undefined;

  const { listIds, checkedInList, allChecked, selBusy } = selectionOf(rows, checked, busy);

  // ── actions ── (each answer carries the Creator the user acted on: another Creator's page drops it)
  async function run(ids: number[], fn: () => Promise<unknown>) {
    const account = accountId;
    dispatch({ type: "runStart", ids });
    let error: string | null = null;
    try {
      await fn();
    } catch (e) {
      error = extractError(e);
    } finally {
      dispatch({ type: "runEnd", ids, error, account });
    }
  }

  function deleteScripts(ids: number[]) {
    const one = ids.length === 1;
    if (!confirm(`${one ? "Delete script?" : `Delete ${ids.length} scripts?`}\n\nThis script will also be deleted from sequences that utilized this script.`)) return;
    void run(ids, async () => {
      for (const id of ids) await deleteM.mutateAsync(id);
    });
  }

  function removeScripts(ids: number[]) {
    const from = inTag ?? inSeq;
    if (!from) return;
    const kind = inTag ? "tag" : "sequence";
    if (!confirm(kind === "tag"
      ? "Remove this script?\n\nThe script will be removed from this tag."
      : "Remove this script?\n\nRemove this script from this sequence. You can add the script back any time you want.")) return;
    // Unchecked once the server took it (`runEnd`); a failed remove keeps the ticks for a retry.
    void run(ids, async () => {
      await relabelM.mutateAsync({ kind, from, ids });
    });
  }

  /** Add script, seeded with the open tag, or the open sequence's next step. */
  function addScript() {
    if (inTag) startNewReply({ tags: [inTag] });
    else if (inSeq) startNewReply({ scriptId: inSeq, scriptStep: String(nextStep(sequences.get(inSeq) ?? [])) });
    else startNewReply();
  }

  /** A tag no script carries lives on this page only: renamed and deleted here, never on the server. */
  const pageOnly = (kind: EntryKind, name: string) => kind === "tag" && pending.includes(name);

  /** The open name modal's props, from the page as it is this render (see `NamePrompt`). */
  function promptProps(p: NamePrompt): Omit<ComponentProps<typeof NameModal>, "onClose"> {
    if (p.kind === "sequence") {
      return {
        title: "Add sequence", label: "Sequence name", maxLength: SCRIPT_NAME_MAX,
        onOk: (name) => {
          if (sequences.has(name)) throw new Error("Sequence name already exists. Please rename sequence.");
          dispatch({ type: "open", kind: "sequence", name });
          startNewReply({ scriptId: name, scriptStep: "1" });
        },
      };
    }
    if (p.kind === "tag") {
      const { ids } = p;
      return {
        title: "Add tag name", label: "Tag name", maxLength: SCRIPT_TAG_MAX,
        options: ids ? tagNames : undefined,
        onOk: async (name) => {
          if (ids?.length) await relabelM.mutateAsync({ kind: "tag", to: name, ids });
          dispatch({ type: "addTag", name, pending: !ids?.length && !tagCounts.has(name) });
        },
      };
    }
    const { entry: kind, from } = p;
    return {
      title: kind === "tag" ? "Modify tag name" : "Modify sequence name",
      label: kind === "tag" ? "Tag name" : "Sequence name",
      initial: from,
      maxLength: kind === "tag" ? SCRIPT_TAG_MAX : SCRIPT_NAME_MAX,
      onOk: async (to) => {
        if (to === from) return;
        if (!pageOnly(kind, from)) await relabelM.mutateAsync({ kind, from, to });
        dispatch({ type: "renameEntry", kind, from, to, order: orderOf(kind), account: accountId });
      },
    };
  }

  function deleteEntry(kind: EntryKind, name: string) {
    const ok = kind === "tag"
      ? confirm("Delete tag?\n\nThis tag will be permanently removed from the script library. Its scripts stay.")
      : confirm("Delete the Sequence?\n\nAre you sure you want to delete this sequence? Its scripts stay in the library.");
    if (!ok) return;
    const done = () => dispatch({ type: "deleteEntry", kind, name, order: orderOf(kind), account: accountId });
    // A page-only tag moves on at once; anything else once the server has dropped it.
    if (pageOnly(kind, name)) done();
    else void run([], async () => { await relabelM.mutateAsync({ kind, from: name }); done(); });
  }

  const sideKind = kindOf(view);

  // ── render ──
  const tagItems: SidebarItem[] = [
    { id: ALL, name: "All scripts", count: replies.length, fixed: true },
    ...tagNames.map((t) => ({ id: t, name: t, count: tagCounts.get(t) ?? 0 })),
    { id: UNCATEGORIZED, name: "Uncategorized", count: replies.filter((r) => !(r.tags ?? []).length).length, fixed: true },
  ];
  const seqItems: SidebarItem[] = seqNames.map((s) => ({ id: s, name: s, count: sequences.get(s)?.length ?? 0 }));
  const showEmptyPanel =
    !replyQ.isLoading && !replyQ.error &&
    ((view === "sequences" && seqNames.length === 0) || (view === "tags" && replies.length === 0 && tagNames.length === 0));

  const activeSeqRows = activeSeq ? sequences.get(activeSeq) ?? [] : [];
  const gap = view === "sequences" && activeSeq ? firstGap(activeSeqRows) : null;
  const fmt = (iso?: string | null) => (iso ? new Date(iso).toLocaleString() : "--");
  const { created, modified } = sequenceDates(activeSeqRows);

  const list = (
    <div className="flex-1 min-w-0">
      {view === "sequences" && activeSeq && (
        // The sequence header (#60, #61): name, then its meta; Add step adds the next step's script.
        <div className="px-4 py-3 border-b border-border">
          <div className="flex items-center gap-2 flex-wrap">
            <Workflow size={20} aria-hidden />
            <h2 className="text-base font-semibold">{activeSeq}</h2>
            <button
              type="button"
              onClick={() => startNewReply({ scriptId: activeSeq, scriptStep: String(nextStep(activeSeqRows)) })}
              className="ml-auto h-7 px-2 rounded text-sm text-accent bg-accent/15 inline-flex items-center gap-1"
            >
              <Plus size={14} aria-hidden /> Add step
            </button>
          </div>
          <div className="mt-1 flex flex-wrap gap-x-4 text-xs text-fg-dim">
            <span>Created on{"："}{fmt(created)}</span>
            <span>Last modified on{"："}{fmt(modified)}</span>
          </div>
          {gap != null && (
            <div className="mt-1 text-xs text-warn">
              No script at step {gap}: the chat&apos;s next-step suggestion stops before it.
            </div>
          )}
        </div>
      )}

      {/* #34 to #36: a 32px bar, 0 16px padding; the select-all box, then the switch; the sort (#33) at the right,
          two 32px antd selects, so Manage scripts' bar grows by 4px either side. */}
      <div className={cn("h-8 px-4 flex items-center gap-2", view === "manage" && "h-10")}>
        <input
          type="checkbox"
          aria-label="Select all"
          checked={allChecked}
          disabled={listIds.length === 0}
          onChange={(e) => dispatch({ type: "setChecked", ids: e.target.checked ? listIds : [] })}
          className="accent-accent"
        />
        <button
          type="button"
          role="switch"
          aria-checked={expanded}
          onClick={() => setExpanded((e) => !e)}
          className="flex items-center gap-2 text-xs text-fg-dim"
        >
          Expand scripts
          <span
            aria-hidden
            className={cn("relative inline-block w-7 h-4 rounded-full transition-colors", expanded ? "bg-accent" : "bg-border")}
          >
            <span
              className={cn("absolute top-0.5 w-3 h-3 rounded-full bg-white transition-all", expanded ? "left-3.5" : "left-0.5")}
            />
          </span>
        </button>
        {view === "manage" && (
          <div className="ml-auto flex items-center gap-2">
            <IfSelect aria-label="Sort by" value={sort.by} onChange={(by) => dispatch({ type: "sortBy", by })} className="w-[120px]"
              options={[{ value: "recent", label: "Recent" }, { value: "name", label: "Name" }]} />
            {/* 120px clips "Descending" at antd's padding, so this one is 136px. */}
            <IfSelect aria-label="Sort order" value={sort.order} onChange={(order) => dispatch({ type: "sortOrder", order })} className="w-[136px]"
              options={[{ value: "asc", label: "Ascending" }, { value: "desc", label: "Descending" }]} />
          </div>
        )}
      </div>

      {/* #51: the selection bar. */}
      {checkedInList.length > 0 && (
        <div
          role="toolbar"
          aria-label="Selection"
          className="mx-4 mb-2 min-h-10 px-3 py-1 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg bg-accent text-white text-sm whitespace-nowrap"
        >
          <span>Selected</span>
          <span className="font-semibold">{checkedInList.length}</span>
          <button type="button" aria-label="Clear selection" onClick={clearSelection} className="rounded bg-black/20 p-0.5">
            <X size={16} aria-hidden />
          </button>
          <div className="ml-auto flex flex-wrap items-center gap-x-4 gap-y-1">
            <button type="button" onClick={() => openModal({ kind: "name", prompt: { kind: "tag", ids: checkedInList } })} disabled={selBusy}
              className="inline-flex items-center gap-1 disabled:opacity-50">
              <List size={16} aria-hidden /> Add to tag
            </button>
            {removeLabel ? (
              <button type="button" onClick={() => removeScripts(checkedInList)} disabled={selBusy}
              className="inline-flex items-center gap-1 disabled:opacity-50">
                <MinusCircle size={16} aria-hidden /> {removeLabel}
              </button>
            ) : (
              <button type="button" onClick={() => deleteScripts(checkedInList)} disabled={selBusy}
              className="inline-flex items-center gap-1 disabled:opacity-50">
                <Trash2 size={16} aria-hidden /> Delete
              </button>
            )}
          </div>
        </div>
      )}

      {error && <div className="px-4 py-2 text-sm text-err">{error}</div>}
      {/* The house state lines; the bundle's list has a spinner and no failure line, so they carry the label. */}
      {replyQ.error && (
        <div title={EXTRA_LABEL} className="px-4 py-2 text-sm text-err">
          Failed to load: {replyQ.error.message || "unknown"}
        </div>
      )}
      {replyQ.isLoading && replies.length === 0 && (
        <div title={EXTRA_LABEL} className="px-4 py-2 text-sm text-fg-dim">Loading…</div>
      )}
      {/* #50 */}
      {!replyQ.isLoading && !replyQ.error && rows.length === 0 && (
        <EmptyState size="sm" text="No data" />
      )}
      <ul aria-label="Scripts list">
        {rows.map(({ r, stepLabel }) => (
          <ScriptRow
            key={r.id}
            r={r}
            stepLabel={stepLabel}
            accountId={accountId}
            expanded={expanded}
            checked={checked.has(r.id)}
            onCheck={(on) => dispatch({ type: "check", ids: [r.id], on })}
            onEdit={() => startEditReply(r)}
            onShare={() => openModal({ kind: "share", ids: [r.id] })}
            onDelete={() => (removeLabel ? removeScripts([r.id]) : deleteScripts([r.id]))}
            removeLabel={removeLabel}
            onOpenChip={(kind, name) => dispatch({ type: "open", kind, name })}
            busy={busy.has(r.id)}
          />
        ))}
      </ul>
    </div>
  );

  return (
    // The bundle's page frame: the header, the toolbar and the list run flush across the page, each band ruled off
    // by a 1px bottom border (#18), in no card.
    <div className="flex flex-col min-h-[calc(100dvh-var(--shell-top,3.5rem))]">
      {/* #3, #4: 16px, weight 600, 24px to the creator selector. #7: the tools 24px tall, 16px apart, at the right.
          #11: the bundle shows Share before the script tour has run (`localStorage` "ScriptTour") or to a role with
          ShareScript; ours shows it always (Role enforcement gates the Scripts page as a whole). On a phone the row
          wraps. */}
      <InflowwPageHeader
        title="Scripts"
        className="h-auto min-h-12 flex-wrap gap-y-2 px-3 py-2 sm:h-12 sm:flex-nowrap sm:px-6 sm:py-0"
        actions={
          <div className="flex items-center gap-4 h-6">
            <button type="button" disabled title={NOT_WIRED} className={HEADER_BOX}>
              <BookOpen size={18} className="mr-1" aria-hidden />
              Learn
            </button>
            <button
              type="button"
              disabled={replies.length === 0}
              onClick={() => openModal({ kind: "share", ids: checkedInList.length ? checkedInList : undefined })}
              className={HEADER_BOX}
            >
              <Share2 size={18} className="mr-1" aria-hidden />
              Share
            </button>
            <MoreMenu
              onAddScript={addScript}
              onAddSequence={() => openModal({ kind: "name", prompt: { kind: "sequence" } })}
              onAddTag={() => openModal({ kind: "name", prompt: { kind: "tag" } })}
              onImportExcel={() => openModal({ kind: "excel" })}
              onImportCreators={() => openModal({ kind: "import" })}
            />
          </div>
        }
      />

      <CreatorRail creators={{ accounts, value: accountId, onChange: pickCreator }} className="flex flex-col">
        {/* #18: 56px tall, 0 24px padding, a 1px bottom border; on a phone 12px, wrapping the right box under the tabs. */}
        <div className="min-h-14 px-3 sm:px-6 py-2 sm:py-0 flex flex-wrap items-center gap-y-2 border-b border-border">
          {view === "manage" ? (
            // #31, #32: Manage scripts swaps the tabs for a back arrow and its title.
            <div className="flex items-center gap-4">
              <button type="button" aria-label="Back" onClick={() => dispatch({ type: "view", view: "tags" })} className="text-fg-dim hover:text-fg">
                <ArrowLeft size={20} aria-hidden />
              </button>
              <h2 className="text-base font-semibold">Manage scripts</h2>
            </div>
          ) : (
            <div role="tablist" aria-label="Scripts" className="flex items-center gap-4 sm:gap-6">
              {(
                [
                  ["tags", "Tag", List],
                  ["sequences", "Sequence", Workflow],
                ] as const
              ).map(([key, label, Icon]) => (
                // #21 to #25: 14px, weight 700, a 24px icon 8px from the text.
                <button
                  key={key}
                  type="button"
                  role="tab"
                  aria-selected={view === key}
                  onClick={() => dispatch({ type: "view", view: key })}
                  className={cn(
                    "h-14 flex items-center gap-2 text-sm font-bold border-b-2",
                    view === key ? "text-fg border-accent" : "text-fg border-transparent",
                  )}
                >
                  <Icon size={24} aria-hidden />
                  {label}
                </button>
              ))}
            </div>
          )}
          <div className="ml-auto flex items-center">
            {/* #26, #27: a 24px search icon, 16px, a 1px by 18px divider, 16px. */}
            {search.open && (
              <input
                type="search"
                autoFocus
                aria-label="Search scripts"
                placeholder="Search"
                value={search.q}
                onChange={(e) => dispatch({ type: "searchQ", q: e.target.value })}
                className="mr-2 w-36 sm:w-48 rounded-md border border-border bg-transparent px-2 py-1 text-sm"
              />
            )}
            <button
              type="button"
              aria-label="Search"
              aria-pressed={search.open}
              onClick={() => dispatch({ type: "searchToggle" })}
              className="mr-4 text-fg-dim hover:text-fg"
            >
              <Search size={24} aria-hidden />
            </button>
            <span aria-hidden className="w-px h-[18px] bg-border mr-4" />
            {/* #28, #29: a 28px pill, 0 8px padding, 4px radius, 14px weight 400. */}
            <button
              type="button"
              aria-pressed={view === "manage"}
              onClick={() => dispatch({ type: "view", view: view === "manage" ? "tags" : "manage" })}
              className="h-7 px-2 whitespace-nowrap rounded text-sm font-normal text-accent bg-bg-elev-2 [html[data-theme=light]_&]:bg-[#eff4ff]"
            >
              Manage scripts
            </button>
          </div>
        </div>

        {showEmptyPanel ? (
          <SequenceEmpty onCreate={() => openModal({ kind: "name", prompt: { kind: "sequence" } })} />
        ) : sideKind === null ? (
          list
        ) : (
          <div className="flex flex-1 flex-col md:flex-row">
            <Sidebar
              kind={sideKind}
              items={sideKind === "tag" ? tagItems : seqItems}
              selected={sideKind === "tag" ? activeTag : activeSeq}
              onSelect={(id) => dispatch({ type: "open", kind: sideKind, name: id })}
              onRename={(i) => openModal({ kind: "name", prompt: { kind: "rename", entry: sideKind, from: i.name } })}
              onDelete={(i) => deleteEntry(sideKind, i.name)}
            />
            {list}
          </div>
        )}
      </CreatorRail>

      {draft?.kind === "reply" && (
        <ScriptEditModal
          title={draft.id != null ? "Edit script" : "Add script"}
          saving={saving}
          onClose={() => setDraft(null)}
        >
          <TemplateDraftEditor
            script
            draft={draft}
            setDraft={setDraft}
            accountId={accountId}
            saving={saving}
            saveErr={saveErr}
            onSave={save}
            tagOptions={tagNames}
            sequenceOptions={seqNames}
          />
        </ScriptEditModal>
      )}

      {namePrompt && <NameModal {...promptProps(namePrompt)} onClose={closeModal} />}
      {modal?.kind === "excel" && <ExcelImportDialog accountId={accountId} onClose={closeModal} />}
      {(modal?.kind === "import" || modal?.kind === "share") && (
        <CopyScriptsDialog
          mode={modal.kind}
          accountId={accountId}
          accounts={accounts}
          ids={modal.kind === "share" ? modal.ids : undefined}
          onClose={closeModal}
          onCopied={modal.kind === "share" ? clearSelection : undefined}
        />
      )}
    </div>
  );
}
