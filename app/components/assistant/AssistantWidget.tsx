"use client";


import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef, useState, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { ArrowUp, ChevronDown, ChevronLeft, ChevronRight, History, LifeBuoy, MousePointerClick, X } from "lucide-react";

import { IfMark } from "@/components/auth/SiteLook";

import { useOptionalChatter } from "@/contexts/ChatterContext";
import { useEmployee } from "@/contexts/EmployeeContext";
import { useOptionalUser } from "@/contexts/UserContext";
import { useAppCreator } from "@/contexts/PageCreatorContext";
import { useAccounts } from "@/hooks/useAccounts";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { useTheme } from "@/hooks/useTheme";
import { useFlags } from "@/components/shell/useFlags";
import { useDragPress } from "@/components/useDragPress";
import { relay, relayFile, type AccountMeta } from "@/lib/relay";
import { saveBlob } from "@/lib/csv";
import { cn } from "@/lib/utils";
import { lazyModule, useLazyModule } from "@/lib/lazyModule";
import { fanDeepLinkHref, isPopoutRoute, sessionGrantedPages } from "@/lib/nav";
import { useAppliedSettings } from "@/lib/appliedSettings";
import { isChatterOnly } from "@/lib/session";
import { BRAND_NAME } from "@/lib/brand";
import {
  appFocusOf, assistantReducer, canGeneralOf, HISTORY_LIMIT, historyFromRows, initialAssistantState,
  cardFocus, sendFocusOf, settledFrom, settledFromError, threadsOf, turnsOf,
  type AskResponse, type AssistantCore, type Focus, type HistoryRow, type ThreadSummary, type Turn,
} from "./assistantReducer";
import { useBodyScrollLock } from "./useBodyScrollLock";
import { AgentBridgeProvider, createAgentBridge } from "./agentBridge";
import { AgentCursor } from "./AgentCursor";
import { CARD, DoPill, DoThread, pillFor, type DoCallbacks } from "./DoMode";
import { flowForHref, type DoDraft } from "./doFlows";
import { exportRunBody } from "./doExport";
import { editApplyBody, editResultsOf } from "./massEdit";
import { doOfferOf, doRunReducer, draftFrom, initialDoRun, previousOf, type DoOffer, type DoRun } from "./doRunReducer";
import { useDoRunner } from "./useDoRunner";
import { FocusLine } from "./FocusLine";
import { canOpenChats, commandLinks, confirmation, openablePages, prepass, type PrepassHit } from "./prepass";
import { ThreadList } from "./ThreadList";
import { SupportButton, SupportPanel } from "./SupportPanel";
import {
  initialSupportEntry, NO_SUPPORT, SUPPORT_POLL_MS, supportEntryReducer, supportStatusOf, type SupportStatus,
} from "./supportReducer";
import { UltraPanel, UltraToggle, useUltraMode } from "@/components/ultra/UltraPanel";
import {
  initialLauncherState, launcherDockReducer, launcherSpot, parseLauncherDock,
} from "./launcherDockReducer";

export type { Turn } from "./assistantReducer";

const OPEN_KEY = "chatterly:assistant_open";
export const LAUNCHER_KEY = "chatterly:assistant_launcher_v2";

export const HELP_PATH = "/help-center";

// Mirrors MAX_QUESTION_CHARS in service/assistant_api.py: past it pydantic 422s, the one failure the 200-always contract doesn't cover.
const MAX_QUESTION_CHARS = 1000;

const NO_ACCOUNT_HINT =
  "No account connected yet — answers come from the manual. To connect one: Creators → Manage creators → Add creator.";
const NO_ACCOUNT_CHATTER = "No creator assigned to you yet — ask your agency to share one, then ask here.";


interface AssistantState extends Pick<AssistantCore, "hydrated" | "open" | "unread" | "active" | "held"> {
  toggle: () => void;
  ask: (question: string) => void;
  command: (question: string) => PrepassHit | null;
  accountId: Focus | undefined;
  accounts: AccountMeta[];
  rosterLoaded: boolean;
  isUser: boolean;
  canChat: boolean;
  openPages: ReadonlySet<string>;
  canGeneral: boolean;
  appFocus: Focus;
  shown: Turn[];
  threads: ThreadSummary[];
  pick: (focus: Focus) => void;
  newChat: () => void;
  openThread: (t: ThreadSummary) => void;
  userName: string | null;
  doOffer: DoOffer;
  doRun: DoRun;
  enterDo: () => void;
  exitDo: () => void;
  sendDo: (request: string) => void;
  doFromQuestion: (question: string) => void;
  doCallbacks: DoCallbacks;
  support: SupportStatus;
  markSupportRead: () => void;
}

// Not crypto.randomUUID: it needs a secure context and a phone on the LAN over http has none.
const newThreadId = () => `t${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;

const AssistantContext = createContext<AssistantState | null>(null);
const NO_ACCOUNTS: AccountMeta[] = [];

export function AssistantProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(assistantReducer, initialAssistantState);
  const { hydrated, open, history, turns, unread, active, held } = state;
  const pathname = usePathname();
  const router = useRouter();
  const [doRun, doDispatch] = useReducer(doRunReducer, initialDoRun);
  const [bridge] = useState(createAgentBridge);
  const [capsOf, setCapsOf] = useState<{ key: string; body: { can_do?: unknown; reason?: unknown } | null } | null>(null);
  const doThread = useRef<string | null>(null);
  useEffect(() => { dispatch({ type: "route", onHelpPage: pathname === HELP_PATH }); }, [pathname]);
  const nextId = useRef(0);

  const accountsQ = useAccounts();
  // Only fetched data is a roster: a chatter's loading query carries `accounts: []`, which would read as nothing connected.
  const owned = accountsQ.dataUpdatedAt > 0 ? accountsQ.data?.accounts : undefined;
  const { current } = useEmployee();
  const employeeId = current?.id ?? null;
  const user = useOptionalUser()?.user;
  const chatter = useOptionalChatter()?.chatter;
  const userName = user?.username ?? chatter?.username ?? null;
  const principal = user?.user_id ?? (chatter?.chatter_id ? `chatter:${chatter.chatter_id}` : null);
  useEffect(() => {
    dispatch({ type: "principal", id: principal });
    doDispatch({ type: "exit" });
    doThread.current = null;
  }, [principal]);

  const appFocus = useAppCreator();
  useEffect(() => { dispatch({ type: "scope", focus: appFocus }); }, [appFocus]);
  const ids = useMemo(() => owned?.map((a) => a.id) ?? null, [owned]);
  const isUser = !!user;
  useEffect(() => { dispatch({ type: "roster", ids, isUser }); }, [ids, isUser]);
  const accountId = sendFocusOf(state);

  useEffect(() => {
    let stored = false;
    try {
      stored = window.localStorage.getItem(OPEN_KEY) === "1";
    } catch {
    }
    dispatch({ type: "hydrate", open: stored });
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    // Never persist the pre-hydration default.
    try { window.localStorage.setItem(OPEN_KEY, open ? "1" : "0"); } catch {}
  }, [hydrated, open]);

  const toggle = useCallback(() => dispatch({ type: "toggle" }), []);

  const [supportBy, setSupportBy] = useState<Record<string, SupportStatus>>({});
  const support = (principal && supportBy[principal]) || NO_SUPPORT;
  const loadSupport = useCallback((who: string) => {
    void Promise.resolve()
      .then(() => relay.get<unknown>("/admin/support/unread"))
      .then((body) => setSupportBy((cur) => ({ ...cur, [who]: supportStatusOf(body) })))
      .catch(() => {});
  }, []);
  useEffect(() => {
    if (hydrated && principal) loadSupport(principal);
  }, [hydrated, principal, loadSupport]);
  const supportOn = support.configured || !(principal && principal in supportBy);
  useEffect(() => {
    if (!supportOn || !principal) return;
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") loadSupport(principal);
    }, SUPPORT_POLL_MS);
    return () => window.clearInterval(id);
  }, [supportOn, principal, loadSupport]);
  const markSupportRead = useCallback(() => {
    if (principal) setSupportBy((cur) => (cur[principal] ? { ...cur, [principal]: { ...cur[principal], unread: 0 } } : cur));
  }, [principal]);

  const wantHistory = hydrated && (open || state.onHelpPage) && state.historyStatus === "idle";
  const asWho = state.principal;
  useEffect(() => {
    if (!wantHistory) return;
    dispatch({ type: "history_requested" });
    relay.get<{ turns: HistoryRow[] }>(`/admin/assistant/history?limit=${HISTORY_LIMIT}`)
      .then((body) => dispatch({ type: "history_loaded", turns: historyFromRows(body), principal: asWho }))
      .catch(() => dispatch({ type: "history_failed" }));
  }, [wantHistory, asWho]);

  const ask = useCallback(async (question: string, sentByDo = false) => {
    if (accountId === undefined) return;
    const id = nextId.current++;
    const thread = active ?? newThreadId();
    dispatch({ type: "asked", id, question, ts: new Date().toISOString(), thread, accountId, fromDo: sentByDo });
    try {
      // No `role` or history in the body: the server derives who is asking from the session and reads the thread's earlier turns itself.
      const r = await relay.post<AskResponse>(
        "/admin/assistant/ask",
        accountId ? { question, account_id: accountId, thread_id: thread } : { question, thread_id: thread },
        { accountId, employeeId },
      );
      dispatch(settledFrom(id, r));
    } catch (e) {
      dispatch(settledFromError(id, e));
    }
  }, [accountId, employeeId, active]);

  const wantCaps = hydrated && (open || state.onHelpPage) && !!accountId;
  const capsKey = `${principal ?? ""}|${accountId ?? ""}`;
  useEffect(() => {
    if (!wantCaps || !accountId) return;
    let live = true;
    relay.get<{ can_do?: unknown; reason?: unknown }>(`/admin/assistant/do-caps?account_id=${encodeURIComponent(accountId)}`, { accountId, employeeId })
      .then((body) => { if (live) setCapsOf({ key: capsKey, body: body ?? null }); })
      .catch(() => {});
    return () => { live = false; };
  }, [wantCaps, accountId, employeeId, capsKey]);
  const doOffer = doOfferOf(capsOf && capsOf.key === capsKey ? capsOf.body : null, isUser);
  const navigate = useCallback((href: string) => router.push(href), [router]);
  const cursor = useDoRunner({ run: doRun, dispatch: doDispatch, bridge, navigate, employeeId });
  const editDraft = doRun.phase === "running" && doRun.draft.flow === "mass_edit" ? doRun.draft : null;
  const applied = useRef<DoDraft | null>(null);
  useEffect(() => {
    if (!editDraft || editDraft.flow !== "mass_edit" || !editDraft.slots || applied.current === editDraft) return;
    // One apply POST per started draft.
    applied.current = editDraft;
    const { slots, account_id: acct } = editDraft;
    relay.post<unknown>("/admin/assistant/edit/apply", editApplyBody(acct, slots), { accountId: acct, employeeId })
      .then((r) => doDispatch({ type: "applied", results: editResultsOf(r, slots) }))
      .catch((e: unknown) => doDispatch({ type: "fail", msg: e instanceof Error && e.message ? e.message : "The change didn't go through" }));
  }, [editDraft, employeeId]);
  const exportRun = doRun.phase === "running" && doRun.draft.flow === "report_export" ? doRun : null;
  const exportKey = exportRun ? `${exportRun.id}|${exportRun.attempt}` : null;
  const downloaded = useRef<string | null>(null);
  useEffect(() => {
    if (!exportRun || !exportKey || exportRun.draft.flow !== "report_export" || downloaded.current === exportKey) return;
    // Keyed on plan id + attempt: Try again is a new attempt of the same draft object, so an object key would hang it.
    downloaded.current = exportKey;
    const slots = exportRun.draft.slots;
    const body = exportRunBody(slots);
    if (!slots || !body) { doDispatch({ type: "fail", msg: "Some names didn't match — fix them and ask again" }); return; }
    relayFile("/admin/reports/run", { employeeId }, body)
      .then(({ blob, name }) => {
        const file = name || slots.filename;
        saveBlob(file, blob);
        doDispatch({ type: "downloaded", file });
      })
      .catch((e: unknown) => doDispatch({ type: "fail", msg: e instanceof Error && e.message ? e.message : "The report didn't build" }));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once per (plan id, attempt), not per run object
  }, [exportKey, employeeId]);
  useEffect(() => { if (accountId !== undefined) doDispatch({ type: "focus", accountId }); }, [accountId]);
  const enterDo = useCallback(() => doDispatch({ type: "enter" }), []);
  const exitDo = useCallback(() => doDispatch({ type: "exit" }), []);
  const sendDo = useCallback(async (request: string) => {
    if (accountId === undefined) return;
    const id = newThreadId();
    const previous = previousOf(doRun);
    const thread = previous && doThread.current ? doThread.current : (doThread.current = newThreadId());
    doDispatch({ type: "draft", id, request, accountId });
    try {
      const r = await relay.post<DoDraft>(
        "/admin/assistant/draft",
        { request, ...(accountId ? { account_id: accountId } : {}), thread_id: thread, ...(previous ? { previous } : {}) },
        { accountId, employeeId },
      );
      doDispatch({ type: "drafted", id, draft: draftFrom(r, accountId) });
    } catch (e) {
      const detail = e instanceof Error && e.message ? ` (${e.message})` : "";
      doDispatch({ type: "fail", id, msg: `Couldn't reach the assistant${detail} — try again in a moment.` });
    }
  }, [accountId, employeeId, doRun]);
  const doFromQuestion = useCallback((question: string) => {
    doDispatch({ type: "enter" });
    void sendDo(question);
  }, [sendDo]);
  const startRun = useCallback((type: "start" | "skipAnimation") => {
    doDispatch({ type });
    if (!open) dispatch({ type: "toggle" });
  }, [open]);
  const { theme, setTheme } = useTheme();
  const appliedSettings = useAppliedSettings().data;
  const flags = useFlags();
  const chatterOnly = isChatterOnly(user, chatter);
  const isMaster = user?.is_admin === true;
  const navFilter = useMemo(() => ({
    chatterOnly, grantedPages: sessionGrantedPages(chatterOnly, appliedSettings?.permissions), master: isMaster, flags,
  }), [chatterOnly, appliedSettings?.permissions, flags, isMaster]);
  const commandTargets = useMemo(() => commandLinks(navFilter), [navFilter]);
  const openPages = useMemo(() => openablePages(navFilter), [navFilter]);
  const command = useCallback((question: string): PrepassHit | null => {
    const hit = prepass(question, commandTargets);
    if (!hit) return null;
    doDispatch({ type: "exit" });
    const id = nextId.current++;
    const focus = accountId ?? null;
    dispatch({ type: "asked", id, question, ts: new Date().toISOString(), thread: active ?? newThreadId(), accountId: focus });
    // A command is a confirmation line, never a server turn (rowId null), so nothing of it reaches the model's history.
    const done = (answer: string) => dispatch({ type: "settled", id, answer, error: null, rowId: null });
    if (hit.kind === "navigate") {
      router.push(hit.href);
      done(confirmation(hit));
    } else if (hit.kind === "theme") {
      const next = hit.theme === "toggle" ? (theme === "dark" ? "light" : "dark") : hit.theme;
      setTheme(next);
      done(confirmation(hit, next));
    } else if (!focus) {
      done(`Pick a model first — @${hit.handle}'s chat belongs to one model.`);
    } else {
      relay.get<{ id?: number | string | null }>(`/api/of/v2/users/${encodeURIComponent(hit.handle)}`, { accountId: focus, employeeId })
        .then((u) => {
          if (u?.id == null || u.id === "") throw new Error("no such fan");
          router.push(fanDeepLinkHref(focus, u.id));
          done(confirmation(hit));
        })
        .catch(() => done(`Couldn't find @${hit.handle} on this model.`));
    }
    return hit;
  }, [commandTargets, accountId, active, router, theme, setTheme, employeeId]);

  const doCallbacks = useMemo<DoCallbacks>(() => ({
    start: () => startRun("start"),
    skipAnimation: () => startRun("skipAnimation"),
    cancel: () => doDispatch({ type: "reset" }),
    stop: () => doDispatch({ type: "abort", reason: "Stopped" }),
    askAsQuestion: (request: string) => { doDispatch({ type: "exit" }); void ask(request, true); },
  }), [startRun, ask]);

  const pick = useCallback((focus: Focus) => dispatch({ type: "pick", focus }), []);
  const newChat = useCallback(() => dispatch({ type: "new_chat" }), []);
  const openThread = useCallback(
    (t: ThreadSummary) => dispatch({ type: "open_thread", thread: t.id, focus: t.focus }), []);

  const shown = useMemo(() => turnsOf(active, history, turns), [active, history, turns]);
  const threads = useMemo(() => threadsOf(history, turns), [history, turns]);
  const rosterIds = state.roster.ids;
  const accounts = useMemo(() => {
    if (rosterIds === null) return NO_ACCOUNTS;
    const meta = new Map((owned ?? []).map((a) => [a.id, a]));
    return rosterIds.flatMap((id) => meta.get(id) ?? []);
  }, [rosterIds, owned]);
  const value: AssistantState = {
    hydrated, open, unread, active, held, toggle, ask, command, accountId,
    accounts, rosterLoaded: rosterIds !== null, isUser: state.roster.isUser, canChat: canOpenChats(commandTargets), openPages,
    canGeneral: canGeneralOf(state.roster),
    appFocus: appFocusOf(state),
    shown, threads,
    pick, newChat, openThread, userName,
    doOffer, doRun, enterDo, exitDo, sendDo, doFromQuestion, doCallbacks,
    support, markSupportRead,
  };
  return (
    <AssistantContext.Provider value={value}>
      <AgentBridgeProvider bridge={bridge}>{children}</AgentBridgeProvider>
      {cursor && <AgentCursor cursor={cursor} />}
    </AssistantContext.Provider>
  );
}

export function useAssistant(): AssistantState {
  const v = useContext(AssistantContext);
  if (!v) throw new Error("useAssistant needs an <AssistantProvider> above it");
  return v;
}


export function AssistantWidget() {
  const a = useAssistant();
  const pathname = usePathname();
  const onMessagesPro = isPopoutRoute(pathname ?? "/");
  const phone = useMediaQuery("(max-width: 767.98px)");
  const [expanded, setExpanded] = useState<DoRun | null>(null);
  const unread = a.unread || a.support.unread > 0;

  if (!a.hydrated || pathname === HELP_PATH || onMessagesPro) return null;

  if (phone) {
    return (
      <>
        {a.open && (pillFor(a.doRun, expanded)
          ? <DoPill run={a.doRun} onStop={a.doCallbacks.stop} onOpen={() => setExpanded(a.doRun)} />
          : <AssistantPanel variant="sheet" onClose={a.toggle} />)}
        <PhoneLauncher hidden={a.open} unread={unread} onOpen={a.toggle} />
      </>
    );
  }

  return (
    <>
      {a.open && <AssistantPanel variant="dock" onClose={a.toggle} />}
      <button
        type="button"
        data-assistant-ui
        onClick={a.toggle}
        className={cn(
          "fixed bottom-5 right-5 z-40 grid place-items-center",
          "h-12 w-12 rounded-full bg-black text-white",
          "shadow-[0_4px_16px_rgba(0,0,0,0.35)] transition-transform hover:scale-105",
        )}
        title={a.open ? "Close help" : "Ask for help with this product"}
        aria-expanded={a.open}
        aria-label="Help assistant"
      >
        {a.open ? <ChevronDown className="h-6 w-6" aria-hidden /> : <LauncherIcon />}
        {unread && !a.open && (
          <span
            className="absolute right-0 top-0 h-3 w-3 rounded-full bg-[#e5372f]"
            aria-label="New reply"
          />
        )}
      </button>
    </>
  );
}

function PhoneLauncher({ hidden, unread, onOpen }: { hidden: boolean; unread: boolean; onOpen: () => void }) {
  const [s, dispatch] = useReducer(launcherDockReducer, initialLauncherState);

  useEffect(() => {
    let raw: string | null = null;
    try { raw = window.localStorage.getItem(LAUNCHER_KEY); } catch { }
    dispatch({ type: "load", dock: parseLauncherDock(raw), vw: window.innerWidth, vh: window.innerHeight });
    const onResize = () => dispatch({ type: "resize", vw: window.innerWidth, vh: window.innerHeight });
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  useEffect(() => {
    if (s.saves === 0) return;
    try { window.localStorage.setItem(LAUNCHER_KEY, JSON.stringify(s.dock)); } catch {}
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s.saves]);

  const { onPointerDown, swallowClick } = useDragPress({
    begin: (e) => {
      const r = e.currentTarget.getBoundingClientRect();
      return { x: r.left, y: r.top };
    },
    move: (o, dx, dy) => dispatch({ type: "dragMove", x: o.x + dx, y: o.y + dy }),
    drop: () => dispatch({ type: "drop" }),
  });

  if (!s.loaded || hidden) return null;
  const { left, top } = launcherSpot(s);
  const dot = unread && (
    <span className="absolute right-0 top-0 h-3 w-3 rounded-full bg-[#e5372f]" aria-label="New reply" />
  );

  if (s.dock.tucked) {
    const onLeft = s.dock.edge === "left";
    return (
      <button
        key="tab"
        type="button"
        onClick={() => { if (!swallowClick()) dispatch({ type: "untuck" }); }}
        style={{ top }}
        className={cn(
          "fixed z-40 grid h-12 w-6 place-items-center bg-black text-white",
          "shadow-[0_4px_16px_rgba(0,0,0,0.35)]",
          onLeft ? "left-0 rounded-r-xl" : "right-0 rounded-l-xl",
        )}
        title="Show help"
        aria-label="Show help assistant"
      >
        {onLeft ? <ChevronRight className="h-5 w-5" aria-hidden /> : <ChevronLeft className="h-5 w-5" aria-hidden />}
        {dot}
      </button>
    );
  }

  return (
    <button
      key="icon"
      type="button"
      onPointerDown={onPointerDown}
      // swallowClick: the release that tucked the icon must not land here and pull it straight back out.
      onClick={() => { if (!swallowClick()) onOpen(); }}
      style={{ left, top }}
      className={cn(
        "fixed z-40 grid h-12 w-12 touch-none select-none place-items-center rounded-full bg-black text-white",
        "shadow-[0_4px_16px_rgba(0,0,0,0.35)]",
        !s.drag && "transition-[left,top] duration-200 ease-out",
      )}
      title="Ask for help with this product (drag to move, push past the edge to tuck away)"
      aria-label="Help assistant"
      data-edge={s.drag ? "dragging" : s.dock.edge}
    >
      <LauncherIcon />
      {dot}
    </button>
  );
}

function LauncherIcon() {
  return (
    <svg viewBox="0 0 28 30" className="h-6 w-6" aria-hidden>
      <path d="M5 1h18a5 5 0 0 1 5 5v23l-6.5-4H5a5 5 0 0 1-5-5V6a5 5 0 0 1 5-5z" fill="currentColor" />
      <path d="M7.5 14.5c3.6 3.2 9.4 3.2 13 0" fill="none" stroke="black" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}


const answerText = lazyModule(() => import("./AnswerText"));

const VARIANT = {
  dock: {
    frame: cn(
      "fixed bottom-[84px] right-5 z-40",
      "w-[400px] h-[min(704px,calc(100dvh-104px))] rounded-2xl",
      "shadow-[0_8px_40px_rgba(0,0,0,0.35)]",
    ),
    column: "",
    composerPad: "",
    inputText: "text-[14px]",
    closeOnNavigate: false,
    lockPage: false,
  },
  page: {
    frame: "relative h-chat min-h-0 w-full",
    column: "mx-auto w-full max-w-[720px]",
    composerPad: "",
    inputText: "text-[14px]",
    closeOnNavigate: false,
    lockPage: false,
  },
  sheet: {
    frame: "fixed inset-x-0 top-[var(--vvt,0px)] z-50 h-[var(--vvh,100dvh)] w-full",
    column: "",
    composerPad: "pb-[max(1rem,env(safe-area-inset-bottom))]",
    // 16px: iOS zooms the page into any smaller input.
    inputText: "text-[16px]",
    closeOnNavigate: true,
    lockPage: true,
  },
} as const;

export function AssistantPanel({
  variant,
  onClose,
}: {
  variant: "dock" | "page" | "sheet";
  onClose?: () => void;
}) {
  const {
    shown, threads, active, held, userName, accounts, rosterLoaded, isUser, accountId, canGeneral, appFocus, canChat, openPages,
    ask, command, pick, newChat, openThread,
    doOffer, doRun, enterDo, exitDo, sendDo, doFromQuestion, doCallbacks, support, markSupportRead,
  } = useAssistant();
  const answer = useLazyModule(answerText);
  const [ultra, setUltra] = useUltraMode(isUser);
  const [draft, setDraft] = useState("");
  const [listOpen, setListOpen] = useState(false);
  const [supportEntry, supportTo] = useReducer(supportEntryReducer, initialSupportEntry);
  const listRef = useRef<HTMLDivElement | null>(null);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);
  const doOn = doRun.phase !== "off";
  const doBusy = doRun.phase === "drafting" || doRun.phase === "running";
  const canSend = draft.trim().length > 0 && accountId !== undefined && !(doOn && doBusy);
  const empty = shown.length === 0 && !doOn;
  const v = VARIANT[variant];
  useBodyScrollLock(v.lockPage);
  const leave = v.closeOnNavigate ? onClose : undefined;
  const column = v.column;
  const accountIds = useMemo(() => (rosterLoaded ? accounts.map((a) => a.id) : null), [accounts, rosterLoaded]);
  const text = (body: string, muted = false, focus: Focus = null) => answer
    ? <answer.AnswerText text={body} muted={muted} onNavigate={leave} focus={focus} accountIds={accountIds} canChat={canChat} pages={openPages} />
    : <span className="whitespace-pre-wrap">{body}</span>;

  useEffect(() => {
    const el = listRef.current;
    // Scroll the list box, not a sentinel: scrollIntoView walks up to the nearest scrollable ancestor, which on a short page is the document.
    if (el) el.scrollTop = el.scrollHeight;
  }, [shown]);

  const supportButton = support.configured
    ? <SupportButton unread={support.unread > 0} onClick={() => supportTo({ type: "open" })} />
    : null;

  if (supportEntry.open && support.configured) {
    return (
      <SupportPanel frame={v.frame} column={column} composerPad={v.composerPad} inputText={v.inputText}
        unread={support.unread} draft={supportEntry.draft} onEntry={supportTo}
        onBack={() => supportTo({ type: "close" })} onClose={onClose} onRead={markSupportRead} />
    );
  }

  if (ultra) {
    return (
      <UltraPanel frame={v.frame} column={column} composerPad={v.composerPad} inputText={v.inputText}
        onClose={onClose} onOff={() => setUltra(false)} headerAction={supportButton} />
    );
  }

  const send = () => {
    if (!canSend) return;
    const q = draft.trim().slice(0, MAX_QUESTION_CHARS);
    const hit = command(q);
    if (hit) {
      if (hit.kind !== "theme") leave?.();
    } else if (doOn) sendDo(q);
    else ask(q);
    setDraft("");
  };
  const offersDo = (body: string) => !!answer && answer.findPaths(body, openPages).some((h) => flowForHref(h.href) !== null);

  const lastTurnId = shown.length > 0 ? shown[shown.length - 1].id : null;
  const renderTurn = (t: Turn) => (
    <div key={t.id} className="flex flex-col gap-2">
      <div className="self-end max-w-[85%] rounded-2xl rounded-br-md bg-fg text-panel px-3.5 py-2 text-[13px] whitespace-pre-wrap break-words">
        {t.question}
      </div>
      {t.answer === null ? (
        <div className="self-start rounded-2xl rounded-bl-md bg-bg-elev-1 px-3.5 py-2 text-[13px] text-fg-dim animate-pulse">
          thinking…
        </div>
      ) : (
        <div
          className={cn(
            "self-start max-w-[92%] rounded-2xl rounded-bl-md bg-bg-elev-1 px-3.5 py-2",
            "text-[13px] leading-relaxed break-words",
            t.error ? "text-fg-dim" : "text-fg",
          )}
        >
          {text(t.answer, !!t.error, cardFocus(t))}
        </div>
      )}
      {doOffer.enabled && t.answer !== null && !t.error && !t.fromDo && offersDo(t.answer) && (
        <button
          type="button"
          onClick={() => doFromQuestion(t.question)}
          className="self-start flex h-8 items-center gap-1.5 rounded-full border border-border-light bg-panel px-3 text-[13px] font-medium text-fg hover:border-muted"
          title="Opens the page and fills it in for you — saved OFF"
        >
          <MousePointerClick className="h-4 w-4" aria-hidden />Do it for me
        </button>
      )}
      {support.configured && t.id === lastTurnId && t.answer !== null && (
        <button
          type="button"
          onClick={() => supportTo({ type: "contact", question: t.question })}
          className="self-start flex h-8 items-center gap-1.5 rounded-full border border-border-light bg-panel px-3 text-[13px] font-medium text-fg hover:border-muted"
          title="Message a real person on the team — your question is copied in, nothing is sent until you press send"
        >
          <LifeBuoy className="h-4 w-4" aria-hidden />Contact support
        </button>
      )}
    </div>
  );

  return (
    <div
      data-look={variant === "page" ? undefined : "messenger"}
      data-assistant-ui
      className={cn("flex flex-col bg-panel text-fg overflow-hidden", v.frame, variant === "dock" && doRun.phase === "running" && "z-[60]")}
    >
      <div
        className={cn(
          "shrink-0 pt-[37px] text-white",
          empty
            ? "pb-[120px] bg-[linear-gradient(180deg,#242424_0%,#2d2d2d_63%,#2d2d2d_72%,var(--color-panel)_100%)]"
            : "pb-10 bg-[linear-gradient(180deg,#242424_0%,#2d2d2d_55%,var(--color-panel)_100%)]",
        )}
      >
        <div className={cn("px-10", column)}>
          <div className="flex h-8 items-center gap-5">
            {(active !== null || doOn) && (
              <button
                type="button"
                onClick={doOn ? exitDo : newChat}
                disabled={doRun.phase === "running"}
                className="-ml-6 -mr-3 grid h-8 w-8 place-items-center rounded-md text-white hover:bg-white/10 disabled:opacity-40"
                title={doOn ? "Back — leave Do it for me" : "Back — start a new chat"}
                aria-label={doOn ? "Leave Do it for me" : "New chat"}
              >
                <ChevronLeft className="h-5 w-5" aria-hidden />
              </button>
            )}
            <IfMark className="size-7" />
            <span className="text-[18px] font-bold">{BRAND_NAME.toUpperCase()}</span>
            <span className="-mr-4 ml-auto flex items-center gap-1">
              {supportButton}
              {threads.length > 0 && (
                <button
                  type="button"
                  onClick={() => setListOpen(true)}
                  className="grid h-8 w-8 place-items-center rounded-md text-white hover:bg-white/10"
                  title="Earlier conversations"
                  aria-label="Earlier conversations"
                >
                  <History className="h-[18px] w-[18px]" aria-hidden />
                </button>
              )}
              {onClose && (
                <button
                  type="button"
                  onClick={onClose}
                  className="grid h-8 w-8 place-items-center rounded-md text-white hover:bg-white/10"
                  title="Close"
                  aria-label="Close help"
                >
                  <X className="h-5 w-5" aria-hidden />
                </button>
              )}
            </span>
          </div>
          {empty ? (
            <h2 className="mt-[70px] text-[30px] font-bold leading-[1.1] text-[#fafafa]">
              Hi {userName || "there"} <span aria-hidden>👋</span>
              <br />
              How can we help?
            </h2>
          ) : (
            <p className="mt-2 text-[12px] text-white/60">
              {doOn ? "Do it for me — opens the page and fills it in" : "Ask how something works, or paste a fan to ask why"}
            </p>
          )}
        </div>
      </div>

      <div ref={listRef} className={cn(empty ? "-mt-[91px]" : "-mt-6", "flex-1 min-h-0 overflow-y-auto overscroll-contain pb-3")}>
        <div className={cn("px-5 flex flex-col gap-3", column)}>
          {empty && (
            <>
              {doOffer.show && (
                <div className="flex flex-col gap-1.5">
                  <button
                    type="button"
                    disabled={!doOffer.enabled}
                    onClick={() => { enterDo(); composerRef.current?.focus({ preventScroll: true }); }}
                    className={cn(CARD, "flex items-center gap-4 text-left",
                      doOffer.enabled ? "hover:border-border-light" : "cursor-not-allowed opacity-60")}
                  >
                    <span className="min-w-0 flex-1">
                      <span className="block text-[15px] font-semibold text-fg">Do it for me</span>
                      <span className="block text-[15px] text-fg-dim">Opens the page and fills it in</span>
                    </span>
                    <MousePointerClick className="h-5 w-5 shrink-0 text-fg" aria-hidden />
                  </button>
                  {doOffer.hint && <div className="px-1 text-[13px] text-fg-dim" data-testid="do-hint">{text(doOffer.hint, true)}</div>}
                </div>
              )}
              {threads.length > 0 && (
                <button
                  type="button"
                  onClick={() => setListOpen(true)}
                  className={cn(CARD, "flex items-center gap-4 text-left hover:border-border-light")}
                >
                  <History className="h-[22px] w-[22px] shrink-0 text-fg" aria-hidden />
                  <span className="min-w-0 flex-1">
                    <span className="block text-[15px] font-semibold text-fg">Earlier conversations</span>
                    <span className="block text-[15px] text-fg-dim">
                      {threads.length} conversation{threads.length === 1 ? "" : "s"} · last {WHEN.format(new Date(threads[0].last))}
                    </span>
                  </span>
                  <ChevronRight className="h-5 w-5 shrink-0 text-fg" aria-hidden />
                </button>
              )}
            </>
          )}
          {doOn ? <DoThread run={doRun} on={doCallbacks} text={text} /> : shown.map(renderTurn)}
        </div>
      </div>

      <div className="shrink-0 border-t border-border bg-panel">
        <div className={cn("px-4 pt-2.5 pb-4 flex flex-col gap-2", v.composerPad, column)}>
          {accounts.length > 0 && accountId !== undefined ? (
            <FocusLine
              focus={accountId} accounts={accounts} canGeneral={canGeneral} started={active !== null}
              held={held} appFocus={appFocus} onPick={pick} onNewChat={newChat}
            />
          ) : rosterLoaded && accounts.length === 0 && (
            <div className="px-1 text-[11px] leading-4 text-muted">{isUser ? text(NO_ACCOUNT_HINT) : NO_ACCOUNT_CHATTER}</div>
          )}
          {doOn && isUser && accountId === null && accounts.length > 0 && (
            <div className="px-1 text-[11px] leading-4 text-muted">No model picked — I can export a report; pick a model above to set up its page.</div>
          )}
          <div className="flex items-end gap-2 rounded-3xl border border-border bg-panel py-1.5 pl-4 pr-1.5 focus-within:border-fg-dim">
            <textarea
              ref={composerRef}
              value={draft}
              onChange={(e) => setDraft(e.target.value.slice(0, MAX_QUESTION_CHARS))}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
              placeholder={doOn ? "What should I set up?" : "Ask a question…"}
              title={doOn
                ? "Describe what to set up; you get a plan to check before anything is filled in. Enter to send · Shift+Enter for a new line"
                : "Answers come from the product manual; 'not supported' is a real answer. Enter to send · Shift+Enter for a new line"}
              rows={1}
              className={cn(
                "flex-1 min-w-0 max-h-28 resize-none bg-transparent py-1.5 leading-5 text-fg placeholder:text-muted focus:outline-none [field-sizing:content]",
                v.inputText,
              )}
            />
            <button
              type="button"
              onClick={send}
              disabled={!canSend}
              className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-fg text-panel transition-opacity disabled:opacity-25"
              aria-label="Ask"
              title="Send"
            >
              <ArrowUp className="h-4 w-4" aria-hidden />
            </button>
          </div>
          {isUser && <UltraToggle checked={false} onChange={setUltra} className="self-end px-1 text-muted" />}
        </div>
      </div>

      {listOpen && (
        <ThreadList
          threads={threads}
          active={active}
          accounts={accounts}
          onPick={(t) => { openThread(t); setListOpen(false); }}
          onClose={() => setListOpen(false)}
        />
      )}
    </div>
  );
}

const WHEN = new Intl.DateTimeFormat("en-US", {
  month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
});
