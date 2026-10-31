"use client";

/**
 * FunnelEditor — create / edit one mass-message funnel (W8-P1), on top of the
 * funnels CRUD API (service/funnels_api.py). A funnel is GLOBAL: an opener
 * (`opening_message`, sent by send_mass_message) plus an ordered list of steps
 * reply_mass_funnel walks per replying fan. Two step shapes:
 *
 *   REPLY — poll the fan on `check_intervals_min`, then send one of a message
 *           VARIANT pool (first ≤2 used) or generate via `prompt`/`generate`.
 *   PPV   — sales copy at a price (`type:"paid_ppv"`).
 *
 * This editor is TEXT-ONLY. PPV MEDIA is per-account (vault ids don't carry
 * between models), so each model maps its own via the FunnelMediaPane ("Media"
 * action in `MassFunnelsTab`) — NOT here.
 *
 * `MassFunnelsTab` is the list (Infloww's legacy table, page-parity ticket 16)
 * with the editor and the delete confirm as dialogs: My Automations > Auto
 * Funnel.
 */

import { Fragment, useEffect, useMemo, useState, type ReactNode } from "react";
import { Plus } from "lucide-react";

import { Badge, Button, Input } from "@/components/ui/primitives";
import { EmptyState, IF_TABLE, IfButton, IfInput, IfLearn, IfModal } from "@/components/ui/infloww";
import { ConfirmDelete, EDITOR_MODAL, FieldLabel, SwitchRow, TABLE_EMPTY } from "@/components/automations/automationPage";
import { cn } from "@/lib/utils";
import { FunnelLaunchPanel } from "@/components/automations/FunnelLaunchPanel";
import { FunnelMediaPane } from "@/components/automations/FunnelMediaPane";
import { ImportCaptionsButton } from "@/components/compose/ImportCaptionsButton";
import {
  useCreateFunnel,
  useDeleteFunnel,
  useFunnel,
  useFunnels,
  useUpdateFunnel,
} from "@/hooks/useFunnels";
import {
  editFunnel, EMPTY_FUNNEL, FUNNEL_RAW, funnelDraftOf, saveBody,
  type DraftStep, type FunnelBody, type FunnelEdit,
} from "@/lib/funnelDraft";
import { canSubmit, useRawJson } from "@/lib/rawJsonReducer";
import {
  useAutomationRules,
  useCreateRule,
  useUpdateRule,
} from "@/hooks/useAutomations";

/** The poller that actually advances funnels past the opener is a per-account
 *  recurring `reply_mass_funnel` automation rule. The opener (send_mass_message)
 *  is funnel-linked, but no reply/PPV step moves while this rule is missing or
 *  disabled — so the tab surfaces & toggles it. Default cadence: every 2 min. */
const WALKER_KIND = "reply_mass_funnel";
const WALKER_EVERY_S = 120;
/** reply_mass_funnel._step_texts: a static step sends its first 2 messages. */
const FUNNEL_STEP_MSGS = 2;

// ── Single-funnel editor ────────────────────────────────────────────────

export function FunnelEditor({
  funnelId,
  onClose,
  onSaved,
}: {
  funnelId: number | null; // null = create
  onClose: () => void;
  onSaved?: () => void;
}) {
  const isEdit = funnelId != null;
  const fullQ = useFunnel(funnelId);
  const createM = useCreateFunnel();
  const updateM = useUpdateFunnel();

  const [seeded, setSeeded] = useState(!isEdit);
  // The draft + the raw-JSON escape hatch (lib/rawJsonReducer): hand-edit the
  // whole funnel body `{ name, opening_message, description, steps }` (paste
  // steps, tweak a field the form doesn't expose). Unknown step keys pass
  // through; see lib/funnelDraft for how known keys and `step` numbers are kept.
  const [draft, dispatch] = useRawJson(FUNNEL_RAW, () => EMPTY_FUNNEL);
  const { name, description, opening, steps } = draft.value;
  const edit = (e: FunnelEdit) => dispatch({ type: "update", fn: (d) => editFunnel(d, e) });
  const fail = (error: string) => dispatch({ type: "fail", error });

  // Seed once from the loaded funnel (edit mode). Create mode starts blank.
  useEffect(() => {
    if (seeded || !fullQ.data) return;
    dispatch({ type: "set", value: funnelDraftOf(fullQ.data) });
    setSeeded(true);
  }, [fullQ.data, seeded, dispatch]);

  const busy = createM.isPending || updateM.isPending;

  async function save() {
    if (!canSubmit(draft)) return; // the raw buffer's parse error is already shown
    let body: FunnelBody;
    try {
      body = saveBody(draft.value);
    } catch (e) {
      return fail((e as Error).message);
    }
    try {
      if (isEdit && funnelId != null) {
        await updateM.mutateAsync({ id: funnelId, ...body });
      } else {
        await createM.mutateAsync(body);
      }
      onSaved?.();
      onClose();
    } catch (e) {
      fail((e as Error)?.message || "Save failed");
    }
  }

  if (isEdit && fullQ.isLoading && !seeded) {
    return <IfModal width={722} title="Edit funnel" onClose={onClose}><p className="text-muted">Loading funnel…</p></IfModal>;
  }
  if (isEdit && fullQ.isError) {
    return (
      <IfModal width={722} title="Edit funnel" onClose={onClose} footer={<IfButton onClick={onClose}>Close</IfButton>}>
        <p className="text-err">{(fullQ.error as Error)?.message || "Failed to load funnel"}</p>
      </IfModal>
    );
  }

  return (
    <IfModal
      width={722}
      title={isEdit ? `Edit funnel · ${name || funnelId}` : "New funnel"}
      onClose={onClose}
      className={EDITOR_MODAL}
      footer={(
        <>
          <IfButton onClick={onClose} disabled={busy}>Cancel</IfButton>
          <IfButton variant="primary" onClick={save} disabled={busy}>
            {busy ? "Saving…" : isEdit ? "Save changes" : "Create funnel"}
          </IfButton>
        </>
      )}
    >
    <div className="space-y-4">
      <div className="hidden justify-end md:flex">
        <button
          type="button"
          onClick={() => dispatch({ type: draft.raw ? "close" : "open" })}
          className="text-[14px] text-accent hover:text-accent-hover"
        >
          {draft.raw ? "← Typed fields" : "Edit raw JSON →"}
        </button>
      </div>

      {draft.raw ? (
        <div className="space-y-2">
          <textarea
            value={draft.text}
            onChange={(e) => dispatch({ type: "edit", text: e.target.value })}
            rows={16}
            spellCheck={false}
            className="w-full rounded-lg bg-bg border border-border text-[11px] font-mono px-2 py-1.5 text-fg focus:outline-none focus:ring-2 focus:ring-accent/40"
            placeholder='{ "name": "…", "opening_message": "…", "steps": [] }'
          />
          <div className="text-[10px] text-fg-dim leading-relaxed">
            Edit the whole funnel body by hand —{" "}
            <code className="text-accent">name</code>,{" "}
            <code className="text-accent">opening_message</code>,{" "}
            <code className="text-accent">description</code>, and the ordered{" "}
            <code className="text-accent">steps</code> array (reply / paid_ppv).
            PPV media stays per-model (set via the Media action), not here.
          </div>
        </div>
      ) : (
      <>
      {/* Header: name + description + opener. */}
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <FieldLabel htmlFor="funnel-name">Name</FieldLabel>
          <IfInput id="funnel-name" value={name} onChange={(e) => edit({ type: "header", patch: { name: e.target.value } })} placeholder="e.g. strokes" className="w-full" />
        </div>
        <div>
          <FieldLabel htmlFor="funnel-description">Description (optional)</FieldLabel>
          <IfInput
            id="funnel-description"
            value={description}
            onChange={(e) => edit({ type: "header", patch: { description: e.target.value } })}
            placeholder="what this funnel is for"
            className="w-full"
          />
        </div>
      </div>
      <div>
        <FieldLabel htmlFor="funnel-opening">Opening message</FieldLabel>
        <textarea
          id="funnel-opening"
          value={opening}
          onChange={(e) => edit({ type: "header", patch: { opening: e.target.value } })}
          rows={3}
          placeholder="The first message sent to the audience (the funnel opener)…"
          className="w-full bg-bg border border-border rounded-md px-3 py-2 text-sm placeholder:text-muted focus:outline-none focus:border-accent resize-y"
        />
      </div>

      {/* Ordered step list. */}
      <div className="space-y-2">
        <div className="text-[11px] uppercase tracking-wide text-fg-dim">
          Steps <span className="opacity-60">({steps.length})</span>
        </div>
        {steps.length === 0 && (
          <div className="text-[11px] text-fg-dim italic">
            No follow-up steps yet — the opener sends and the funnel ends. Add a
            reply step to chase a response, or a PPV step to sell.
          </div>
        )}
        {steps.map((s, i) => (
          <StepCard
            key={i}
            index={i}
            total={steps.length}
            step={s}
            onPatch={(patch) => edit({ type: "patchStep", i, patch })}
            onRemove={() => edit({ type: "removeStep", i })}
            onMove={(dir) => edit({ type: "moveStep", i, dir })}
            onMsgChange={(mi, text) => edit({ type: "patchMsg", i, mi, text })}
            onMsgAdd={() => edit({ type: "addMsg", i })}
            onMsgImport={(texts) => edit({ type: "addMsgs", i, texts })}
            onMsgRemove={(mi) => edit({ type: "removeMsg", i, mi })}
          />
        ))}

        <div className="flex items-center gap-2">
          <Button size="sm" variant="secondary" onClick={() => edit({ type: "addStep", kind: "reply" })}>
            + Reply step
          </Button>
          <Button size="sm" variant="secondary" onClick={() => edit({ type: "addStep", kind: "ppv" })}>
            + PPV step
          </Button>
        </div>
      </div>
      </>
      )}

      {draft.error && <div className="text-[12px] text-err whitespace-pre-wrap">{draft.error}</div>}

      <p className="text-[12px] text-muted">
        PPV media is set per model — close this and use the{" "}
        <span className="text-fg">Media</span> action on the funnel to map each
        model&apos;s vault content to its PPV steps.
      </p>
    </div>
    </IfModal>
  );
}

/** One step card: reply / PPV toggle + the per-kind fields. */
function StepCard({
  index,
  total,
  step,
  onPatch,
  onRemove,
  onMove,
  onMsgChange,
  onMsgAdd,
  onMsgImport,
  onMsgRemove,
}: {
  index: number;
  total: number;
  step: DraftStep;
  onPatch: (patch: Partial<DraftStep>) => void;
  onRemove: () => void;
  onMove: (dir: -1 | 1) => void;
  onMsgChange: (mi: number, val: string) => void;
  onMsgAdd: () => void;
  onMsgImport: (texts: string[]) => void;
  onMsgRemove: (mi: number) => void;
}) {
  const isPpv = step.kind === "ppv";
  return (
    <div className="border border-border rounded-md p-3 space-y-2.5">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-[11px] uppercase tracking-wide text-fg-dim">Step {index + 1}</span>
          <Badge color={isPpv ? "warn" : "muted"}>{isPpv ? "paid PPV" : "reply"}</Badge>
        </div>
        <div className="flex items-center gap-2 md:gap-1">
          <button
            type="button"
            onClick={() => onMove(-1)}
            disabled={index === 0}
            className="text-fg-dim hover:text-fg disabled:opacity-30 text-base px-2 py-1 min-w-10 min-h-10 md:text-xs md:px-1 md:py-0 md:min-w-0 md:min-h-0"
            title="Move up"
          >↑</button>
          <button
            type="button"
            onClick={() => onMove(1)}
            disabled={index === total - 1}
            className="text-fg-dim hover:text-fg disabled:opacity-30 text-base px-2 py-1 min-w-10 min-h-10 md:text-xs md:px-1 md:py-0 md:min-w-0 md:min-h-0"
            title="Move down"
          >↓</button>
          <button
            type="button"
            onClick={onRemove}
            className="text-xs px-2 py-1 min-h-10 md:text-[11px] md:px-0 md:py-0 md:min-h-0 text-err hover:underline ml-1"
          >remove</button>
        </div>
      </div>

      {/* Reply / PPV toggle. */}
      <div className="flex items-center gap-1.5">
        <KindChip active={!isPpv} onClick={() => onPatch({ kind: "reply" })} label="Reply" />
        <KindChip active={isPpv} onClick={() => onPatch({ kind: "ppv" })} label="Paid PPV" />
      </div>

      {/* Poll intervals (the walker waits on a PPV step's cadence too). */}
      <label className="block space-y-1">
        <span className="text-[11px] text-fg-dim">
          Check for a reply every <span className="opacity-60">(minutes, comma-separated; blank = default 2, 4, 10)</span>
        </span>
        <Input
          value={step.intervals}
          onChange={(e) => onPatch({ intervals: e.target.value })}
          placeholder="2, 4, 10"
        />
      </label>

      {/* PPV: price + locked-text. MEDIA is per-model → set in the Media pane. */}
      {isPpv && (
        <div className="space-y-2">
          <label className="block space-y-1 max-w-[12rem]">
            <span className="text-[11px] text-fg-dim">Price (USD, whole)</span>
            <Input
              type="number"
              min={0}
              value={step.price}
              onChange={(e) => onPatch({ price: e.target.value })}
              placeholder="default $24"
            />
          </label>
          <div className="text-[11px] text-fg-dim italic">
            🖼 Media for this PPV step is set per model in the funnel&apos;s{" "}
            <span className="text-fg not-italic">Media</span> action (vault ids
            differ per account).
          </div>
          <label className="flex items-center gap-2 text-xs cursor-pointer select-none">
            <input
              type="checkbox"
              checked={step.lockedText}
              onChange={(e) => onPatch({ lockedText: e.target.checked })}
            />
            <span>Lock the text too (fan must pay to read the copy)</span>
          </label>
        </div>
      )}

      {/* Copy: AI-generate toggle, then either a prompt or a variant pool. */}
      <label className="flex items-center gap-2 text-xs cursor-pointer select-none">
        <input
          type="checkbox"
          checked={step.generate}
          onChange={(e) => onPatch({ generate: e.target.checked })}
        />
        <span>Generate the {isPpv ? "sales copy" : "reply"} with AI</span>
      </label>

      {step.generate ? (
        <label className="block space-y-1">
          <span className="text-[11px] text-fg-dim">
            Prompt <span className="opacity-60">(optional — guides the AI; blank uses the default persona)</span>
          </span>
          <textarea
            value={step.prompt}
            onChange={(e) => onPatch({ prompt: e.target.value })}
            rows={2}
            placeholder="e.g. tease the PPV and create urgency…"
            className="w-full bg-bg border border-border rounded-md px-3 py-2 text-sm placeholder:text-muted focus:outline-none focus:border-accent resize-y"
          />
        </label>
      ) : (
        <div className="space-y-1.5">
          <span className="text-[11px] text-fg-dim">
            {isPpv ? "Sales copy" : "Reply"} variants <span className="opacity-60">(one is sent at random; first ≤2 used)</span>
          </span>
          {step.messages.map((m, mi) => (
            <div key={mi} className="flex items-start gap-1.5">
              <textarea
                value={m}
                onChange={(e) => onMsgChange(mi, e.target.value)}
                rows={2}
                placeholder={step.messages.length > 1 ? `Variant ${mi + 1}` : "Message…"}
                className="flex-1 bg-bg border border-border rounded-md px-3 py-2 text-sm placeholder:text-muted focus:outline-none focus:border-accent resize-y"
              />
              {step.messages.length > 1 && (
                <button
                  type="button"
                  onClick={() => onMsgRemove(mi)}
                  title="Remove this variant"
                  className="text-fg-dim hover:text-err text-sm leading-none mt-2"
                >×</button>
              )}
            </div>
          ))}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <button
              type="button"
              onClick={onMsgAdd}
              className="text-[11px] text-accent hover:underline"
            >
              + add variant{step.messages.length > 1 ? ` (${step.messages.length})` : ""}
            </button>
            {/* reply_mass_funnel sends static messages[:2] only. */}
            <ImportCaptionsButton current={step.messages} max={FUNNEL_STEP_MSGS} onImport={onMsgImport} />
          </div>
        </div>
      )}
    </div>
  );
}

function KindChip({ active, onClick, label }: { active: boolean; onClick: () => void; label: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "px-2.5 py-1 rounded-full text-[11px] border transition-colors",
        active
          ? "bg-accent text-white border-accent"
          : "bg-bg-elev-1 text-fg-dim border-border hover:text-fg hover:border-fg-dim",
      )}
    >
      {label}
    </button>
  );
}

// ── Mass-funnels tab: list + create/edit dialogs (Auto Funnel) ──

/** Without a `frame` the header's Learn and "New funnel" sit right above the body. */
const inlineFrame = (actions: ReactNode, body: ReactNode) => (
  <div className="space-y-3">
    <div className="flex items-center justify-end gap-4">{actions}</div>
    {body}
  </div>
);

const FUNNEL_COLUMNS = ["Name", "Steps", "Description", "Actions"] as const;
const LINK = "text-accent hover:text-accent-hover disabled:cursor-not-allowed disabled:opacity-50";

/** The funnels as Infloww's legacy list: a 56px "Reply walking" switch row, then an IF_TABLE (Name, Steps,
 *  Description, Actions fixed right); Start and Media open under their row, the editor and the delete confirm are
 *  dialogs. `frame(actions, body)` places Learn and "New funnel" (Auto Funnel passes them to its page header). */
export function MassFunnelsTab({ accountId, frame = inlineFrame }: {
  accountId: string | null;
  frame?: (actions: ReactNode, body: ReactNode) => ReactNode;
}) {
  const listQ = useFunnels();
  const deleteM = useDeleteFunnel();
  const [editing, setEditing] = useState<number | null>(null);
  const [adding, setAdding] = useState(false);
  const [launching, setLaunching] = useState<number | null>(null);
  const [mediaFor, setMediaFor] = useState<number | null>(null);
  const [deleting, setDeleting] = useState<{ id: number; name: string } | null>(null);
  const [rowErr, setRowErr] = useState<{ id: number; msg: string } | null>(null);

  const funnels = listQ.data ?? [];

  // ── Reply-walker (per-account reply_mass_funnel rule) ──────────────────
  const rulesQ = useAutomationRules(accountId);
  const walker = useMemo(
    () => (rulesQ.data ?? []).find((r) => r.kind === WALKER_KIND) ?? null,
    [rulesQ.data],
  );
  const walkerOn = !!walker?.is_enabled;
  const createRuleM = useCreateRule(accountId);
  const updateRuleM = useUpdateRule(accountId);
  const walkerBusy = createRuleM.isPending || updateRuleM.isPending;
  const [walkerErr, setWalkerErr] = useState<string | null>(null);

  /** Flip the per-account reply-walker on/off (create the rule on first enable). */
  async function setWalker(enabled: boolean) {
    if (!accountId) return;
    setWalkerErr(null);
    try {
      if (walker) {
        await updateRuleM.mutateAsync({ id: walker.id, is_enabled: enabled });
      } else if (enabled) {
        await createRuleM.mutateAsync({
          account_id: accountId,
          kind: WALKER_KIND,
          name: "Reply-walking",
          every_seconds: WALKER_EVERY_S,
          payload: {},
          is_enabled: true,
        });
      }
    } catch (e) {
      setWalkerErr((e as Error)?.message || "Failed to update reply-walking");
    }
  }

  function close() {
    setEditing(null);
    setAdding(false);
  }

  async function remove(id: number) {
    setDeleting(null);
    setRowErr(null);
    try {
      await deleteM.mutateAsync(id);
      if (editing === id) close();
    } catch (e) {
      setRowErr({ id, msg: (e as Error)?.message || "Delete failed" });
    }
  }

  /** One row's panel at a time: Start or Media, toggled. */
  const openPanel = (which: "start" | "media", id: number) => {
    close();
    setLaunching(which === "start" && launching !== id ? id : null);
    setMediaFor(which === "media" && mediaFor !== id ? id : null);
  };

  const line = (children: ReactNode, cls = "text-muted") => (
    <tr><td colSpan={FUNNEL_COLUMNS.length} className={cn("py-10 text-center text-[14px]", cls)}>{children}</td></tr>
  );

  const actions = (
    <>
      <IfLearn tip={<>Funnels are global (shared across all your models). Reference one from a mass send to auto-walk
        the reply / PPV steps per replying fan.</>}>
        <span className="max-sm:sr-only">Learn</span>
      </IfLearn>
      <IfButton variant="primary" icon={Plus} onClick={() => { setEditing(null); setAdding(true); }} className="max-sm:px-2.5">
        <span className="max-sm:sr-only">New funnel</span>
      </IfButton>
    </>
  );

  const body = (
    <div className="space-y-4">
      {/* Reply-walker status + switch. Without it on, funnels send the
          opener but never advance — so make that visible right where they live. */}
      {accountId && (
        <div>
          <SwitchRow
            label="Reply walking"
            hint={walkerOn
              ? `On · every ${Math.round((walker?.every_seconds ?? WALKER_EVERY_S) / 60)} min. Fans who reply to a funnel get walked through its reply / PPV steps.`
              : "Off. Funnels send the opener but won't advance past it until this is on (every 2 min)."}
            checked={walkerOn}
            disabled={walkerBusy}
            onChange={setWalker}
          />
          {walkerErr && <div className="mt-1 text-[12px] text-err">{walkerErr}</div>}
        </div>
      )}

      <div className="overflow-x-auto">
        <table className={cn(IF_TABLE.table, "min-w-[720px]")}>
          <thead>
            <tr>
              {FUNNEL_COLUMNS.map((c) => (
                <th key={c} className={cn(IF_TABLE.th, IF_TABLE.thDivider, "border-b border-border",
                  c === "Actions" && cn(IF_TABLE.fixedRightHead, "z-[1] w-[220px]"))}>
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {listQ.isLoading ? line("Loading…")
              : listQ.isError ? line((listQ.error as Error)?.message || "Failed to load funnels", "text-err")
              : funnels.length === 0 ? (
                <tr><td colSpan={FUNNEL_COLUMNS.length}><EmptyState kind="data" text="No funnels yet" className={TABLE_EMPTY} /></td></tr>
              ) : funnels.map((f) => {
                const open = launching === f.id || mediaFor === f.id;
                return (
                  <Fragment key={f.id}>
                    <tr className={cn(IF_TABLE.row, open && "border-b-0")}>
                      <td className={IF_TABLE.td}>
                        <span className="block truncate">{f.name}</span>
                        {rowErr?.id === f.id && <span className="mt-1 block text-[12px] text-err">{rowErr.msg}</span>}
                      </td>
                      <td className={cn(IF_TABLE.td, "whitespace-nowrap")}>{f.step_count}</td>
                      <td className={cn(IF_TABLE.td, "max-w-[360px] truncate text-fg-dim")}>{f.description || f.opening_message}</td>
                      <td className={cn(IF_TABLE.td, IF_TABLE.fixedRight, "z-[1] w-[220px] whitespace-nowrap")}>
                        <span className="inline-flex gap-4">
                          <button type="button" className={LINK} aria-expanded={mediaFor === f.id} onClick={() => openPanel("media", f.id)}>Media</button>
                          <button type="button" className={LINK} aria-expanded={launching === f.id} onClick={() => openPanel("start", f.id)}>Start</button>
                          <button type="button" className={LINK}
                            onClick={() => { setLaunching(null); setMediaFor(null); setAdding(false); setEditing(f.id); }}>Edit</button>
                          <button type="button" className={LINK} disabled={deleteM.isPending}
                            onClick={() => setDeleting({ id: f.id, name: f.name })}>Delete</button>
                        </span>
                      </td>
                    </tr>
                    {open && (
                      <tr className={IF_TABLE.row}>
                        <td colSpan={FUNNEL_COLUMNS.length} className="space-y-2 px-4 pb-4">
                          {launching === f.id && (
                            <>
                              {!walkerOn && (
                                <div className="flex flex-wrap items-center gap-2 rounded-md border border-warn/40 bg-warn/10 px-3 py-2">
                                  <span className="min-w-[12rem] flex-1 text-[12px] text-warn">
                                    Reply walking is off — this funnel will send the opener
                                    but won&apos;t advance through its reply / PPV steps.
                                  </span>
                                  <IfButton variant="primary" onClick={() => setWalker(true)} disabled={walkerBusy}>
                                    {walkerBusy ? "Enabling…" : "Enable reply walking"}
                                  </IfButton>
                                </div>
                              )}
                              <FunnelLaunchPanel key={accountId ?? ""} funnel={f} accountId={accountId} onClose={() => setLaunching(null)} />
                            </>
                          )}
                          {mediaFor === f.id && (
                            <FunnelMediaPane funnel={f} accountId={accountId} onClose={() => setMediaFor(null)} />
                          )}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
          </tbody>
        </table>
      </div>

      {(adding || editing != null) && (
        <FunnelEditor key={editing ?? "new"} funnelId={editing} onClose={close} />
      )}
      {deleting && (
        <ConfirmDelete
          title={`Delete funnel "${deleting.name}"?`}
          pending={deleteM.isPending}
          onConfirm={() => remove(deleting.id)}
          onClose={() => setDeleting(null)}
        />
      )}
    </div>
  );

  return <>{frame(actions, body)}</>;
}
