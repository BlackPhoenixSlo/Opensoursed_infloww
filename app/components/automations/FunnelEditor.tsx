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
 * The steps show as a timeline of cards (StepCard), one open at a time; the
 * raw JSON sits behind the footer's "Edit as JSON".
 *
 * `MassFunnelsTab` is the list (Infloww's Smart Messages table: status pills,
 * phone rows with a "⋯" menu) with the editor and the delete confirm as
 * dialogs: My Automations > Auto Funnel.
 */

import { Fragment, useEffect, useMemo, useState, type ReactNode } from "react";
import { MoreHorizontal, Plus } from "lucide-react";

import {
  EmptyState, IF_TABLE, IfButton, IfHelp, IfInput, IfLabel, IfLearn, IfModal, IfSwitch, IfTextArea,
} from "@/components/ui/infloww";
import { ConfirmDelete, TABLE_EMPTY } from "@/components/automations/automationPage";
import { Menu } from "@/components/ui/Menu";
import { cn } from "@/lib/utils";
import { FunnelLaunchPanel } from "@/components/automations/FunnelLaunchPanel";
import { FunnelMediaPane } from "@/components/automations/FunnelMediaPane";
import { StepCard } from "@/components/automations/StepCard";
import { funnelStatus, startedAgo, type FunnelStatus } from "@/components/automations/funnelList";
import { StatusPill } from "@/components/automations/StatusPill";
import {
  useCreateFunnel,
  useDeleteFunnel,
  useFunnel,
  useFunnels,
  useUpdateFunnel,
  type FunnelSummary,
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
  // One step card open at a time; editFunnel moves it with its step (funnelDraft.followOpen).
  const { name, description, opening, steps, open } = draft.value;
  const edit = (e: FunnelEdit) => dispatch({ type: "update", fn: (d) => editFunnel(d, e) });
  // Opening a card is not an edit (Escape still closes an untouched draft).
  const toggle = (i: number) => rawDispatch({ type: "update", fn: (d) => editFunnel(d, { type: "toggleStep", i }) });
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
          {/* The JSON escape hatch: reachable, not prominent (fast imports). */}
          <IfButton variant="link" onClick={() => dispatch({ type: draft.raw ? "close" : "open" })}
            className="mr-auto">
            {draft.raw ? "Back to form" : "Edit as JSON"}
          </IfButton>
          <IfButton onClick={onClose} disabled={busy}>Cancel</IfButton>
          <IfButton variant="primary" onClick={save} disabled={busy}>
            {busy ? "Saving…" : isEdit ? "Save changes" : "Create funnel"}
          </IfButton>
        </>
      )}
    >
    <div className="space-y-6">
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
      <section className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <IfLabel htmlFor="funnel-name" required>Name</IfLabel>
            <IfInput id="funnel-name" value={name} onChange={(e) => edit({ type: "header", patch: { name: e.target.value } })}
              placeholder="e.g. strokes" className="w-full" />
          </div>
          <div>
            <IfLabel htmlFor="funnel-description">Description</IfLabel>
            <IfInput id="funnel-description" value={description}
              onChange={(e) => edit({ type: "header", patch: { description: e.target.value } })}
              placeholder="Optional: what it is for" className="w-full" />
          </div>
        </div>
        <div>
          <IfLabel htmlFor="funnel-opening" required>Opening message</IfLabel>
          <IfTextArea id="funnel-opening" value={opening}
            onChange={(e) => edit({ type: "header", patch: { opening: e.target.value } })}
            rows={3} placeholder="The first message, sent to the audience you pick when you start the funnel…" />
        </div>
      </section>

      {/* The follow-up steps as a timeline (Infloww Scripts' sequence steps). */}
      <section>
        <h3 className="text-[14px] font-medium text-fg">Follow-up steps ({steps.length})</h3>
        <IfHelp className="mb-3">
          {steps.length === 0
            ? "No follow-up steps yet: the opener sends and the funnel ends."
            : "Each time a fan replies, the next step goes out, top to bottom."}
        </IfHelp>
        {steps.length > 0 && (
          <ol className="relative space-y-3 before:absolute before:bottom-6 before:left-[13px] before:top-6 before:w-px before:bg-border">
            {steps.map((s, i) => (
              <StepCard
                key={i}
                index={i}
                total={steps.length}
                step={s}
                open={open === i}
                onToggle={() => toggle(i)}
                onPatch={(patch) => edit({ type: "patchStep", i, patch })}
                onRemove={() => edit({ type: "removeStep", i })}
                onMove={(dir) => edit({ type: "moveStep", i, dir })}
              />
            ))}
          </ol>
        )}
        <div className={cn("mt-3 flex flex-wrap items-center gap-2", steps.length > 0 && "pl-10")}>
          <IfButton icon={Plus} onClick={() => edit({ type: "addStep", kind: "reply" })}>Reply step</IfButton>
          <IfButton icon={Plus} onClick={() => edit({ type: "addStep", kind: "ppv" })}>PPV step</IfButton>
        </div>
      </section>
      </>
      )}

      {draft.error && <div className="text-[12px] text-err whitespace-pre-wrap">{draft.error}</div>}
    </div>
    </IfModal>
  );
}

const isFunnelSeed = (a: { type: RawJsonAction<unknown>["type"] }) => a.type === "set" || a.type === "open" || a.type === "close" || a.type === "fail";

// ── Auto Funnel list: header actions, follow-up switch, table, dialogs ──

/** Without a `frame` the header's Learn and "New funnel" sit right above the body. */
const inlineFrame = (actions: ReactNode, body: ReactNode) => (
  <div className="space-y-3">
    <div className="flex items-center justify-end gap-4">{actions}</div>
    {body}
  </div>
);

const FUNNEL_COLUMNS = ["Funnel", "Status", "Steps", "Fans in funnel", "Last started", "Actions"] as const;
/** Below `sm` a row is the Funnel cell (status + fans under the name) and a "⋯" menu. */
const WIDE_ONLY = new Set<string>(["Status", "Steps", "Fans in funnel", "Last started"]);
const LINK = "text-accent hover:text-accent-hover disabled:cursor-not-allowed disabled:opacity-50";

/** The shared pill, or a dash while this creator's stats load. */
function FunnelPill({ status }: { status: FunnelStatus | null }) {
  return status ? <StatusPill status={status} className="leading-[inherit]" /> : <span className="text-muted">—</span>;
}

type RowAction = "Start" | "Edit" | "Media" | "Delete";
const ROW_ACTIONS: RowAction[] = ["Start", "Edit", "Media", "Delete"];

/** Auto Funnel's list (Infloww's Smart Messages table): the "Follow up on replies" switch, then a row per funnel
 *  with this creator's Status, Steps, Fans in funnel and Last started (funnels_api `?account_id=` stats); Start and
 *  Media open under their row, the editor and the delete confirm are dialogs. `frame(actions, body)` places Learn and
 *  "New funnel" (Auto Funnel passes them to its page header). */
export function MassFunnelsTab({ accountId, frame = inlineFrame }: {
  accountId: string | null;
  frame?: (actions: ReactNode, body: ReactNode) => ReactNode;
}) {
  const listQ = useFunnels(accountId);
  const deleteM = useDeleteFunnel();
  // One open at a time: the editor dialog (new or a funnel) or a row's Start / Media panel.
  const [panel, setPanel] = useState<{ k: "new" } | { k: "edit" | "start" | "media"; id: number } | null>(null);
  const openOn = (k: "edit" | "start" | "media", id: number) => panel?.k === k && panel.id === id;
  const [deleting, setDeleting] = useState<{ id: number; name: string } | null>(null);
  const [rowErr, setRowErr] = useState<{ id: number; msg: string } | null>(null);

  const funnels = listQ.data ?? [];

  // ── Follow-ups (the per-account reply_mass_funnel rule, "reply walking") ──
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

  /** Flip the per-account follow-ups on/off (create the rule on first enable). Starting a funnel turns it on
   *  server-side too (mass_queue_api → funnels_api.ensure_funnel_walker). */
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
      setWalkerErr((e as Error)?.message || "Failed to update follow-ups");
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
  const act = (f: FunnelSummary, a: RowAction) => {
    if (a === "Start") openPanel("start", f.id);
    else if (a === "Media") openPanel("media", f.id);
    else if (a === "Edit") setPanel({ k: "edit", id: f.id });
    else setDeleting({ id: f.id, name: f.name });
  };

  const line = (children: ReactNode, cls = "text-muted") => (
    <tr><td colSpan={FUNNEL_COLUMNS.length} className={cn("py-10 text-center text-[14px]", cls)}>{children}</td></tr>
  );

  const actions = (
    <>
      <IfLearn tip={<>A funnel sends an opener to the audience you pick, then one follow-up step each time a fan replies,
        usually ending in a paid PPV. Funnels are global (shared across all your models); each model picks its own PPV
        media under Media.</>}>
        <span className="max-sm:sr-only">Learn</span>
      </IfLearn>
      <IfButton variant="primary" icon={Plus} onClick={() => setPanel({ k: "new" })} className="max-sm:px-2.5">
        <span className="max-sm:sr-only">New funnel</span>
      </IfButton>
    </>
  );

  const everyMin = Math.round((walker?.every_seconds ?? WALKER_EVERY_S) / 60);
  const body = (
    <div className="space-y-4">
      {/* Follow-ups: without them a funnel sends the opener and stops. Starting a funnel turns them on. */}
      {accountId && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
          <IfSwitch label="Follow up on replies" checked={walkerOn} disabled={walkerBusy || rulesQ.isLoading}
            loading={walkerBusy} onChange={setWalker} />
          <span className="text-[12px] text-muted">
            {walkerOn
              ? `On · checks every ${everyMin} min and sends the next step to fans who replied`
              : "Off · steps stop after the opener; starting a funnel turns this on"}
          </span>
          {walkerErr && <span className="text-[12px] text-err">{walkerErr}</span>}
        </div>
      )}

      <div className="overflow-x-auto">
        <table className={cn(IF_TABLE.table, "sm:min-w-[820px]")}>
          <thead>
            <tr>
              {FUNNEL_COLUMNS.map((c) => (
                <th key={c} className={cn(IF_TABLE.th, IF_TABLE.thDivider, "border-b border-border",
                  WIDE_ONLY.has(c) && "max-sm:hidden",
                  c === "Actions" && cn(IF_TABLE.fixedRightHead, "z-[1] w-[220px] max-sm:w-12 max-sm:text-transparent"))}>
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
                // No pill until the follow-up switch has loaded (a running funnel would flash "Paused").
                const status = accountId && rulesQ.isSuccess ? funnelStatus(f.stats, walkerOn) : null;
                const ago = startedAgo(f.stats?.last_started_at);
                const fans = f.stats ? `${f.stats.active_fans} ${f.stats.active_fans === 1 ? "fan" : "fans"} in funnel` : null;
                return (
                  <Fragment key={f.id}>
                    <tr className={cn(IF_TABLE.row, open && "border-b-0")}>
                      <td className={cn(IF_TABLE.td, "w-full max-w-0")}>
                        <span className="block truncate font-medium">{f.name}</span>
                        <span className="block truncate text-[12px] text-muted max-sm:hidden">{f.description || f.opening_message}</span>
                        {/* Phone: the hidden columns, under the name. */}
                        <span className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-muted sm:hidden">
                          <FunnelPill status={status} />
                          {f.stats && f.stats.last_started_at && <span>{fans}{ago && ` · ${ago}`}</span>}
                          {!status && <span>{f.step_count} steps</span>}
                        </span>
                        {rowErr?.id === f.id && <span className="mt-1 block text-[12px] text-err">{rowErr.msg}</span>}
                      </td>
                      <td className={cn(IF_TABLE.td, "whitespace-nowrap max-sm:hidden")}><FunnelPill status={status} /></td>
                      <td className={cn(IF_TABLE.td, "whitespace-nowrap max-sm:hidden")}>{f.step_count}</td>
                      <td className={cn(IF_TABLE.td, "whitespace-nowrap tabular-nums max-sm:hidden")}>{f.stats ? f.stats.active_fans : "—"}</td>
                      <td className={cn(IF_TABLE.td, "whitespace-nowrap text-fg-dim max-sm:hidden")}
                        title={f.stats?.last_started_at ? `${f.stats.last_started_at} UTC` : undefined}>{ago ?? "—"}</td>
                      <td className={cn(IF_TABLE.td, IF_TABLE.fixedRight, "z-[1] w-[220px] whitespace-nowrap max-sm:w-12 max-sm:px-2")}>
                        <span className="inline-flex gap-4 max-sm:hidden">
                          <button type="button" className={LINK} aria-expanded={openOn("start", f.id)} onClick={() => act(f, "Start")}>Start</button>
                          <button type="button" className={LINK} onClick={() => act(f, "Edit")}>Edit</button>
                          <button type="button" className={LINK} aria-expanded={openOn("media", f.id)} onClick={() => act(f, "Media")}>Media</button>
                          <button type="button" className={LINK} disabled={deleteM.isPending} onClick={() => act(f, "Delete")}>Delete</button>
                        </span>
                        <span className="sm:hidden">
                          {/* Phone: the same four actions in a "⋯" menu. */}
                          <Menu label={<MoreHorizontal className="h-4 w-4" aria-hidden />} ariaLabel={`More actions for ${f.name}`}
                            align="right" items={ROW_ACTIONS.map((a) => ({ label: a, onClick: () => act(f, a),
                              disabled: a === "Delete" && deleteM.isPending }))} />
                        </span>
                      </td>
                    </tr>
                    {open && (
                      <tr className={IF_TABLE.row}>
                        <td colSpan={FUNNEL_COLUMNS.length} className="px-4 pb-4 max-sm:px-0">
                          {openOn("start", f.id) && (
                            <FunnelLaunchPanel key={accountId ?? ""} funnel={f} accountId={accountId} followUpsOn={walkerOn} onClose={close} />
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
