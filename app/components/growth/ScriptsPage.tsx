"use client";


import { useEffect, useMemo, useReducer, useRef, useState, type ComponentProps } from "react";
import { ArrowLeft, BookOpen, ImagePlus, List, MinusCircle, Plus, Search, Share2, Trash2, Workflow, X } from "lucide-react";

import { SCRIPT_NAME_MAX, SCRIPT_TAG_MAX, TemplateDraftEditor, extractError } from "@/components/settings/TemplateDraftEditor";
import { useSavedReplyEditor, useScopedAccount } from "@/components/settings/TemplatesTab";
import { AllModelsView } from "@/components/growth/AllModelsView";
import { CopyScriptsDialog, ExcelImportDialog } from "@/components/growth/ScriptsImportDialogs";
import { NameModal, ScriptEditModal } from "@/components/growth/ScriptModals";
import { ScriptFillDialog } from "@/components/growth/ScriptFillDialog";
import {
  ASK_OWNER, SAVE_FIRST, fillKey, fillRefusalText, isLocked, leftText, noticeText, undoPayload, type Action as FillAction,
  type FillNotice,
} from "@/components/growth/scriptFillState";
import { dlAccess } from "@/components/vault/vaultDownloadReducer";
import {
  MoreMenu, NOT_WIRED, ScriptRow, SequenceEmpty, ShowMore, Sidebar, type SidebarItem,
} from "@/components/growth/ScriptsParts";
import { CreatorRail } from "@/components/shell/CreatorRail";
import { EmptyState, IfSelect, InflowwPageHeader } from "@/components/ui/infloww";
import { useActiveAccounts } from "@/hooks/useAccounts";
import { useRenderCap } from "@/hooks/useRenderCap";
import {
  stalePlan, useDeleteSavedReplies, useDeleteSavedReply, useFillApply, useFillUndo, useRelabelSavedReplies,
  useSavedReplySequences,
} from "@/hooks/useSavedReplies";
import { useChatterFolderAccess } from "@/hooks/useVaultMedia";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import { cn } from "@/lib/utils";
import {
  ALL, INITIAL, UNCATEGORIZED, activeEntry, byName, entryIds, firstGap, kindOf, livePending, nextStep, scriptRows,
  scriptsPageReducer, selectionOf, sequenceHeader, sequenceOrder, sequencesOf, tagCountsOf, type EntryKind,
  type Modal, type NamePrompt,
} from "@/components/growth/scriptsPageState";
import { ifConfirm } from "@/components/ui/ifConfirm";

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
  const deleteManyM = useDeleteSavedReplies(accountId);
  const relabelM = useRelabelSavedReplies(accountId);
  const metaQ = useSavedReplySequences(accountId);
  const fillApplyM = useFillApply();
  const fillUndoM = useFillUndo();
  const access = dlAccess(useChatterFolderAccess(accountId));
  const fillReq = useRef(0);
  const fillOut = useRef(new Set<string>());

  const [page, dispatch] = useReducer(scriptsPageReducer, INITIAL);
  const { view, checked, busy, error, modal, search, sort, allModels, fill } = page;
  const fillDispatch = (action: FillAction) => dispatch({ type: "fill", action });
  const [expanded, setExpanded] = useState(false);
  const namePrompt = modal?.kind === "name" ? modal.prompt : null;
  const openModal = (m: Modal) => dispatch({ type: "openModal", modal: m });
  const closeModal = () => dispatch({ type: "closeModal" });
  const clearSelection = () => dispatch({ type: "setChecked", ids: [] });
  const pickCreator = (id: string) => {
    setAccountId(id);
    setDraft(null);
    dispatch({ type: "reset", account: id });
  };
  useEffect(() => {
    if (accountId !== page.account) dispatch({ type: "reset", account: accountId });
  }, [accountId, page.account]);

  const pending = useMemo(() => livePending(page.pendingTags, replies), [page.pendingTags, replies]);
  const tagCounts = useMemo(() => tagCountsOf(replies, pending), [replies, pending]);
  const tagNames = useMemo(() => [...tagCounts.keys()].sort(byName), [tagCounts]);
  const sequences = useMemo(() => sequencesOf(replies), [replies]);
  const metas = useMemo(() => new Map((metaQ.data ?? []).map((m) => [m.name, m])), [metaQ.data]);
  const seqNames = useMemo(
    () => sequenceOrder(metas, sequences, page.seqSort),
    [sequences, metas, page.seqSort],
  );
  const tagOrder = useMemo(() => [ALL, ...tagNames, UNCATEGORIZED], [tagNames]);
  const orderOf = (kind: EntryKind) => (kind === "tag" ? tagOrder : seqNames);
  const activeSeq = activeEntry(page.open.sequence, seqNames);
  const activeTag = activeEntry(page.open.tag, tagOrder) ?? ALL;
  const fillOpen = !allModels && view === "sequences" ? activeSeq : null;
  useEffect(() => dispatch({ type: "fill", action: { type: "show", sequence: fillOpen } }), [fillOpen]);

  const rows = useMemo(
    () => scriptRows({ view, replies, sequences, activeSeq, activeTag, q: search.q, sort }),
    [view, replies, sequences, activeSeq, activeTag, search.q, sort],
  );

  const inTag = view === "tags" && activeTag !== ALL && activeTag !== UNCATEGORIZED ? activeTag : null;
  const inSeq = view === "sequences" ? activeSeq : null;
  const removeLabel = inTag ? "Remove from tag" : inSeq ? "Remove from sequence" : undefined;

  const { listIds, checkedInList, allChecked, selBusy } = selectionOf(rows, checked, busy);

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

  async function deleteScripts(ids: number[]) {
    const one = ids.length === 1;
    if (!(await ifConfirm(`${one ? "Delete script?" : `Delete ${ids.length} scripts?`}\n\nThis script will also be deleted from sequences that utilized this script.`, { danger: true }))) return;
    void run(ids, async () => {
      if (one) await deleteM.mutateAsync(ids[0]);
      else await deleteManyM.mutateAsync(ids);
    });
  }

  async function removeScripts(ids: number[]) {
    const from = inTag ?? inSeq;
    if (!from) return;
    const kind = inTag ? "tag" : "sequence";
    if (!(await ifConfirm(kind === "tag"
      ? "Remove this script?\n\nThe script will be removed from this tag."
      : "Remove this script?\n\nRemove this script from this sequence. You can add the script back any time you want."))) return;
    void run(ids, async () => {
      await relabelM.mutateAsync({ kind, from, ids });
    });
  }

  function addScript() {
    if (inTag) startNewReply({ tags: [inTag] });
    else if (inSeq) startNewReply({ scriptId: inSeq, scriptStep: String(nextStep(sequences.get(inSeq) ?? [])) });
    else startNewReply();
  }

  async function runFill(
    account: string | null, sequence: string, start: "press" | "undoPress",
    call: (pin: { account: string; sequence: string; req: number }) => Promise<FillAction>,
  ) {
    const key = fillKey(account, sequence);
    // Checked and set before the POST: a second press in the same render must send nothing.
    if (!account || fillOut.current.has(key)) return;
    fillOut.current.add(key);
    const pin = { account, sequence, req: ++fillReq.current };
    fillDispatch({ type: start, ...pin });
    try {
      fillDispatch(await call(pin));
    } finally {
      fillOut.current.delete(key);
    }
  }

  function fillPress(sequence: string) {
    return runFill(accountId, sequence, "press", async (pin): Promise<FillAction> => {
      try {
        const r = await fillApplyM.mutateAsync({ account: pin.account, sequence });
        return r.status !== "ok" ? { type: "answered", ...pin, status: r.status } : { type: "applied", ...pin, result: r };
      } catch (e) {
        // 409 stale carries the fresh plan: show and ask again, never apply silently.
        const fresh = stalePlan(e);
        return fresh ? { type: "answered", ...pin, status: fresh.status }
          : { type: "failed", ...pin, message: fillRefusalText(e) };
      }
    });
  }

  function fillUndo(notice: FillNotice) {
    return runFill(notice.account, notice.sequence, "undoPress", async (pin): Promise<FillAction> => {
      try {
        const result = await fillUndoM.mutateAsync({ account: pin.account, ...undoPayload(notice) });
        return { type: "undone", ...pin, result };
      } catch (e) {
        return { type: "failed", ...pin, message: fillRefusalText(e) };
      }
    });
  }

  function reloadList() {
    void replyQ.refetch();
  }

  const pageOnly = (kind: EntryKind, name: string) => kind === "tag" && pending.includes(name);

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

  async function deleteEntry(kind: EntryKind, name: string) {
    const ok = await ifConfirm(kind === "tag"
      ? "Delete tag?\n\nThis tag will be permanently removed from the script library. Its scripts stay."
      : "Delete the Sequence?\n\nAre you sure you want to delete this sequence? Its scripts stay in the library.", { danger: true });
    if (!ok) return;
    const done = () => dispatch({ type: "deleteEntry", kind, name, order: orderOf(kind), account: accountId });
    if (pageOnly(kind, name)) done();
    else void run([], async () => { await relabelM.mutateAsync({ kind, from: name }); done(); });
  }

  const sideKind = kindOf(view);

  const tagItems: SidebarItem[] = useMemo(() => [
    { id: ALL, name: "All scripts", count: replies.length, fixed: true },
    ...tagNames.map((t) => ({ id: t, name: t, count: tagCounts.get(t) ?? 0 })),
    { id: UNCATEGORIZED, name: "Uncategorized", count: replies.filter((r) => !(r.tags ?? []).length).length, fixed: true },
  ], [replies, tagNames, tagCounts]);
  const seqItems: SidebarItem[] = useMemo(
    () => seqNames.map((s) => ({ id: s, name: s, count: sequences.get(s)?.length ?? 0 })),
    [seqNames, sequences],
  );
  const { cap: listShown, hasMore: listHasMore, more: listMore, sentinel: listSentinel } = useRenderCap(
    rows.length, `${view}|${activeTag}|${activeSeq}|${search.q}|${sort.by}|${sort.order}`,
  );
  const showEmptyPanel =
    !replyQ.isLoading && !replyQ.error &&
    ((view === "sequences" && seqNames.length === 0) || (view === "tags" && replies.length === 0 && tagNames.length === 0));

  const activeSeqRows = activeSeq ? sequences.get(activeSeq) ?? [] : [];
  const gap = view === "sequences" && activeSeq ? firstGap(activeSeqRows) : null;
  const fmt = (iso?: string | null) =>
    iso ? new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : "--";
  const { createdBy, created, modified } = sequenceHeader(activeSeq ? metas.get(activeSeq) : undefined, activeSeqRows);
  const editingSeqRow = draft?.kind === "reply" && draft.id != null && activeSeqRows.some((r) => r.id === Number(draft.id));
  // An open edit of a Sequence step blocks Fill: its save is a whole-row PUT that would wipe the Fill.
  const fillBlocked = access !== "all" ? ASK_OWNER : editingSeqRow ? SAVE_FIRST : null;
  const activeKey = activeSeq != null ? fillKey(accountId, activeSeq) : null;
  const fillBusy = activeKey != null && fill.inflight[activeKey] != null;
  const rowLocked = (r: { script_id?: string | null }) => r.script_id != null && isLocked(fill, accountId, r.script_id, replyQ.isError);
  const listStale = activeSeq != null && replyQ.isError;
  const fillNotice = activeKey ? fill.notices[activeKey] : undefined;
  const editingUndoRow = draft?.kind === "reply" && draft.id != null &&
    (fillNotice?.undo.some((u) => u.id === Number(draft.id)) ?? false);
  const fillLeft = activeKey ? fill.left[activeKey] : undefined;

  const list = (
    <div className="flex-1 min-w-0">
      {view === "sequences" && activeSeq && (
        <div className="px-4 py-3 border-b border-border">
          <div className="flex items-center gap-2 flex-wrap">
            <Workflow size={20} aria-hidden />
            <h2 className="text-base font-semibold">{activeSeq}</h2>
            <span title={EXTRA_LABEL} className="ml-auto inline-flex">
              <button
                type="button"
                disabled={fillBlocked != null || fillBusy}
                aria-busy={fillBusy || undefined}
                title={fillBlocked ?? undefined}
                onClick={() => void fillPress(activeSeq)}
                className="h-7 px-2 rounded text-sm text-accent bg-accent/15 inline-flex items-center gap-1 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <ImagePlus size={14} aria-hidden /> Fill with content
              </button>
            </span>
            <button
              type="button"
              onClick={() => startNewReply({ scriptId: activeSeq, scriptStep: String(nextStep(activeSeqRows)) })}
              className="h-7 px-2 rounded text-sm text-accent bg-accent/15 inline-flex items-center gap-1"
            >
              <Plus size={14} aria-hidden /> Add step
            </button>
          </div>
          <div className="mt-1 flex flex-wrap gap-x-4 text-xs text-fg-dim">
            {createdBy && <span>Created by{"："}{createdBy}</span>}
            <span>Created on{"："}{fmt(created)}</span>
            <span>Last modified on{"："}{fmt(modified)}</span>
          </div>
          {gap != null && (
            <div className="mt-1 text-xs text-warn">
              No script at step {gap}: the chat&apos;s next-step suggestion stops before it.
            </div>
          )}
          {fillNotice && (
            <div role="status" aria-label="Fill notice" title={EXTRA_LABEL}
              className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 rounded bg-accent/15 px-2 py-1 text-xs text-fg">
              <span>{noticeText(fillNotice)}</span>
              <span aria-hidden>·</span>
              <button
                type="button"
                disabled={editingSeqRow || editingUndoRow || fillBusy}
                title={editingSeqRow || editingUndoRow ? SAVE_FIRST : undefined}
                onClick={() => void fillUndo(fillNotice)}
                className="text-accent underline disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Undo
              </button>
              {gap != null && (
                <span className="text-warn">No script at step {gap}: the chat&apos;s next-step suggestion stops before it.</span>
              )}
              <button type="button" aria-label="Dismiss Fill notice" onClick={() => fillDispatch({ type: "dismiss", account: accountId, sequence: activeSeq })}
                className="ml-auto text-fg-dim hover:text-fg">
                <X size={14} aria-hidden />
              </button>
            </div>
          )}
          {listStale && (
            <div role="status" title={EXTRA_LABEL} className="mt-2 flex items-center gap-2 text-xs text-warn">
              <span>The list did not reload, so this sequence&apos;s steps stay locked.</span>
              <button type="button" disabled={replyQ.isFetching} onClick={reloadList}
                className="text-accent underline disabled:opacity-50 disabled:cursor-not-allowed">
                Reload
              </button>
            </div>
          )}
          {fillLeft && (
            <div role="status" title={EXTRA_LABEL} className="mt-2 flex items-center gap-2 text-xs text-warn">
              <span>{leftText(fillLeft)}</span>
              <button type="button" aria-label="Dismiss Undo note" onClick={() => fillDispatch({ type: "dismiss", account: accountId, sequence: activeSeq })}
                className="ml-auto text-fg-dim hover:text-fg">
                <X size={14} aria-hidden />
              </button>
            </div>
          )}
        </div>
      )}

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
            <IfSelect aria-label="Sort order" value={sort.order} onChange={(order) => dispatch({ type: "sortOrder", order })} className="w-[136px]"
              options={[{ value: "asc", label: "Ascending" }, { value: "desc", label: "Descending" }]} />
          </div>
        )}
      </div>

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
      {replyQ.error && (
        <div title={EXTRA_LABEL} className="px-4 py-2 text-sm text-err">
          Failed to load: {replyQ.error.message || "unknown"}
        </div>
      )}
      {replyQ.isLoading && replies.length === 0 && (
        <div title={EXTRA_LABEL} className="px-4 py-2 text-sm text-fg-dim">Loading…</div>
      )}
      {!replyQ.isLoading && !replyQ.error && rows.length === 0 && (
        <EmptyState size="sm" text="No data" />
      )}
      <ul aria-label="Scripts list">
        {rows.slice(0, listShown).map(({ r, stepLabel }, i) => (
          <ScriptRow
            key={r.id}
            r={r}
            stepLabel={stepLabel}
            last={i === rows.length - 1}
            accountId={accountId}
            expanded={expanded}
            checked={checked.has(r.id)}
            onCheck={(on) => dispatch({ type: "check", ids: [r.id], on })}
            onEdit={() => startEditReply(r)}
            onShare={() => openModal({ kind: "share", ids: [r.id] })}
            onDelete={() => (removeLabel ? removeScripts([r.id]) : deleteScripts([r.id]))}
            removeLabel={removeLabel}
            onOpenChip={(kind, name) => dispatch({ type: "open", kind, name })}
            busy={busy.has(r.id) || rowLocked(r)}
          />
        ))}
        {listHasMore && (
          <li ref={listSentinel} className="list-none">
            <ShowMore left={rows.length - listShown} onClick={listMore} />
          </li>
        )}
      </ul>
    </div>
  );

  return (
    <div className="flex flex-col min-h-[calc(100dvh-var(--shell-top,3.5rem))]">
      <InflowwPageHeader
        title="Scripts"
        className="h-auto min-h-12 flex-wrap gap-y-2 px-3 py-2 sm:h-12 sm:flex-nowrap sm:px-6 sm:py-0"
        actions={
          !allModels && <div className="flex items-center gap-4 h-8">
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

      <CreatorRail
        creators={{
          accounts, value: allModels ? null : accountId, onChange: pickCreator,
          all: { pick: () => dispatch({ type: "allModels" }) },
        }}
        className="flex flex-col"
      >
        {allModels ? (
          <AllModelsView accounts={accounts} />
        ) : (
        <>
        <div className="min-h-14 px-3 sm:px-6 py-2 sm:py-0 flex flex-wrap items-center gap-y-2 border-b border-border">
          {view === "manage" ? (
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
              onShare={(i) => openModal({ kind: "share", ids: entryIds(sideKind, i.name, replies) })}
              onRename={(i) => openModal({ kind: "name", prompt: { kind: "rename", entry: sideKind, from: i.name } })}
              onDelete={(i) => deleteEntry(sideKind, i.name)}
              sort={sideKind === "sequence" ? page.seqSort : undefined}
              onSort={(by) => dispatch({ type: "seqSort", by })}
            />
            {list}
          </div>
        )}
        </>
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
      {fill.dialog && (
        <ScriptFillDialog
          accountId={accountId}
          dialog={fill.dialog}
          busy={fill.inflight[fillKey(accountId, fill.dialog.sequence)] != null || fillBlocked != null}
          onFill={(sequence) => void fillPress(sequence)}
          onDescribeRefused={({ sequence, req }, message) => fillDispatch({
            type: "describeRefused", account: accountId, sequence, req, message,
          })}
          onClose={() => fillDispatch({ type: "close" })}
        />
      )}
      {modal?.kind === "excel" && <ExcelImportDialog accountId={accountId} onClose={closeModal} />}
      {(modal?.kind === "import" || modal?.kind === "share") && (
        <CopyScriptsDialog
          key={modal.kind}
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
