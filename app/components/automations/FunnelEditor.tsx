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

import {
  EmptyState, IF_TABLE, IfButton, IfHelp, IfInput, IfLabel, IfLearn, IfModal, IfSegmented, IfTextArea,
  type IfOption,
} from "@/components/ui/infloww";
import { ConfirmDelete, SwitchRow, TABLE_EMPTY } from "@/components/automations/automationPage";
import { cn } from "@/lib/utils";
import { FunnelLaunchPanel } from "@/components/automations/FunnelLaunchPanel";
import { FunnelMediaPane } from "@/components/automations/FunnelMediaPane";
import { StepCard } from "@/components/automations/StepCard";
import {
  useCreateFunnel,
  useDeleteFunnel,
  useFunnel,
  useFunnels,
  useUpdateFunnel,
} from "@/hooks/useFunnels";
import {
  editFunnel, EMPTY_FUNNEL, FUNNEL_RAW, funnelDraftOf, saveBody, stepErrorText,
  type FunnelBody, type FunnelEdit,
} from "@/lib/funnelDraft";
import { canSubmit, useRawJson, type RawJsonAction } from "@/lib/rawJsonReducer";
import { useTouched } from "@/components/compose/useTouched";
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

// ── Single-funnel editor ────────────────────────────────────────────────

const EDITOR_MODES: IfOption<"typed" | "raw">[] = [
  { value: "typed", label: "Typed fields" },
  { value: "raw", label: "Raw JSON" },
];

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
  const [draft, rawDispatch] = useRawJson(FUNNEL_RAW, () => EMPTY_FUNNEL);
  // Escape closes only an untouched draft: the load's seed, a mode switch and a failed save are not edits.
  const { touched, dispatch } = useTouched(draft, rawDispatch, isFunnelSeed);
  const { name, description, opening, steps } = draft.value;
  const edit = (e: FunnelEdit) => dispatch({ type: "update", fn: (d) => editFunnel(d, e) });
  const fail = (error: string) => dispatch({ type: "fail", error });

  // Seed once from the loaded funnel (edit mode). Create mode starts blank.
  useEffect(() => {
    if (seeded || !fullQ.data) return;
    rawDispatch({ type: "set", value: funnelDraftOf(fullQ.data) });
    setSeeded(true);
  }, [fullQ.data, seeded, rawDispatch]);

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
      // The server's 422 names steps by step[i] / id → by position, as on the cards.
      fail(stepErrorText((e as Error)?.message || "Save failed", body.steps));
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
      keyboard={!touched && !busy}
      size="editor"
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
      <IfSegmented
        aria-label="Editor mode"
        options={EDITOR_MODES}
        value={draft.raw ? "raw" : "typed"}
        onChange={(m) => dispatch({ type: m === "raw" ? "open" : "close" })}
        className="max-md:hidden"
      />

      {draft.raw ? (
        <div>
          <IfTextArea
            aria-label="Funnel JSON"
            value={draft.text}
            onChange={(e) => dispatch({ type: "edit", text: e.target.value })}
            rows={16}
            spellCheck={false}
            className="font-mono text-[13px]"
            placeholder='{ "name": "…", "opening_message": "…", "steps": [] }'
          />
          <IfHelp>The whole funnel body: name, opening_message, description and the ordered steps (reply / paid_ppv).</IfHelp>
        </div>
      ) : (
      <>
      {/* Header: name + description + opener. */}
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <IfLabel htmlFor="funnel-name" required>Name</IfLabel>
          <IfInput id="funnel-name" value={name} onChange={(e) => edit({ type: "header", patch: { name: e.target.value } })} placeholder="e.g. strokes" className="w-full" />
        </div>
        <div>
          <IfLabel htmlFor="funnel-description">Description</IfLabel>
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
        <IfLabel htmlFor="funnel-opening" required>Opening message</IfLabel>
        <IfTextArea
          id="funnel-opening"
          value={opening}
          onChange={(e) => edit({ type: "header", patch: { opening: e.target.value } })}
          rows={3}
          placeholder="The first message sent to the audience (the funnel opener)…"
        />
      </div>

      {/* Ordered step list. */}
      <div className="space-y-3">
        <div>
          <h3 className="text-[14px] font-medium text-fg">Steps ({steps.length})</h3>
          {steps.length === 0 && (
            <IfHelp>No follow-up steps yet: the opener sends and the funnel ends.</IfHelp>
          )}
        </div>
        {steps.map((s, i) => (
          <StepCard
            key={i}
            index={i}
            total={steps.length}
            step={s}
            onPatch={(patch) => edit({ type: "patchStep", i, patch })}
            onRemove={() => edit({ type: "removeStep", i })}
            onMove={(dir) => edit({ type: "moveStep", i, dir })}
          />
        ))}

        <div className="flex flex-wrap items-center gap-2">
          <IfButton icon={Plus} onClick={() => edit({ type: "addStep", kind: "reply" })}>Reply step</IfButton>
          <IfButton icon={Plus} onClick={() => edit({ type: "addStep", kind: "ppv" })}>PPV step</IfButton>
        </div>
      </div>
      </>
      )}

      {draft.error && <div className="text-[12px] text-err whitespace-pre-wrap">{draft.error}</div>}

      <IfHelp>PPV media is set per model: save, then use the funnel&apos;s Media action.</IfHelp>
    </div>
    </IfModal>
  );
}

const isFunnelSeed = (a: { type: RawJsonAction<unknown>["type"] }) => a.type === "set" || a.type === "open" || a.type === "close" || a.type === "fail";

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
  // One open at a time: the editor dialog (new or a funnel) or a row's Start / Media panel.
  const [panel, setPanel] = useState<{ k: "new" } | { k: "edit" | "start" | "media"; id: number } | null>(null);
  const openOn = (k: "edit" | "start" | "media", id: number) => panel?.k === k && panel.id === id;
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

  const close = () => setPanel(null);

  async function remove(id: number) {
    setDeleting(null);
    setRowErr(null);
    try {
      await deleteM.mutateAsync(id);
      if (openOn("edit", id)) close();
    } catch (e) {
      setRowErr({ id, msg: (e as Error)?.message || "Delete failed" });
    }
  }

  /** One row's panel at a time: Start or Media, toggled. */
  const openPanel = (k: "start" | "media", id: number) => setPanel(openOn(k, id) ? null : { k, id });

  const line = (children: ReactNode, cls = "text-muted") => (
    <tr><td colSpan={FUNNEL_COLUMNS.length} className={cn("py-10 text-center text-[14px]", cls)}>{children}</td></tr>
  );

  const actions = (
    <>
      <IfLearn tip={<>Funnels are global (shared across all your models). Reference one from a mass send to auto-walk
        the reply / PPV steps per replying fan.</>}>
        <span className="max-sm:sr-only">Learn</span>
      </IfLearn>
      <IfButton variant="primary" icon={Plus} onClick={() => setPanel({ k: "new" })} className="max-sm:px-2.5">
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
                const open = openOn("start", f.id) || openOn("media", f.id);
                return (
                  <Fragment key={f.id}>
                    <tr className={cn(IF_TABLE.row, open && "border-b-0")}>
                      <td className={IF_TABLE.td}>
                        <span className="block truncate">{f.name}</span>
                        {rowErr?.id === f.id && <span className="mt-1 block text-[12px] text-err">{rowErr.msg}</span>}
                      </td>
                      <td className={cn(IF_TABLE.td, "whitespace-nowrap")}>{f.step_count}</td>
                      <td className={cn(IF_TABLE.td, "w-full max-w-0 truncate text-fg-dim")}>{f.description || f.opening_message}</td>
                      <td className={cn(IF_TABLE.td, IF_TABLE.fixedRight, "z-[1] w-[220px] whitespace-nowrap")}>
                        <span className="inline-flex gap-4">
                          <button type="button" className={LINK} aria-expanded={openOn("media", f.id)} onClick={() => openPanel("media", f.id)}>Media</button>
                          <button type="button" className={LINK} aria-expanded={openOn("start", f.id)} onClick={() => openPanel("start", f.id)}>Start</button>
                          <button type="button" className={LINK}
                            onClick={() => setPanel({ k: "edit", id: f.id })}>Edit</button>
                          <button type="button" className={LINK} disabled={deleteM.isPending}
                            onClick={() => setDeleting({ id: f.id, name: f.name })}>Delete</button>
                        </span>
                      </td>
                    </tr>
                    {open && (
                      <tr className={IF_TABLE.row}>
                        <td colSpan={FUNNEL_COLUMNS.length} className="space-y-2 px-4 pb-4">
                          {openOn("start", f.id) && (
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
                              <FunnelLaunchPanel key={accountId ?? ""} funnel={f} accountId={accountId} onClose={close} />
                            </>
                          )}
                          {openOn("media", f.id) && (
                            <FunnelMediaPane funnel={f} accountId={accountId} onClose={close} />
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

      {(panel?.k === "new" || panel?.k === "edit") && (
        <FunnelEditor key={panel.k === "edit" ? panel.id : "new"} funnelId={panel.k === "edit" ? panel.id : null} onClose={close} />
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
