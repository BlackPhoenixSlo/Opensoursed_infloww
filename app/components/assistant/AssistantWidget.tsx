"use client";

/**
 * AssistantWidget — the in-product help bot's messenger launcher and panel.
 *
 * Staff ask "how do I make autopost?" and get back WHERE in the UI it lives,
 * WHAT to set, and an honest "not supported" when that is the truth. The
 * thinking is entirely server-side (service/assistant_api.py, closed-book over
 * assistant_manual.md); this file is a composer, a list and one awaited POST.
 * Design record: plans/help-chatbot/README.md.
 *
 * THREE pieces. `AssistantProvider` owns the conversation, the persisted
 * open/closed bit and the account pick, because collapsing UNMOUNTS the panel
 * and a session that forgot the last three answers the moment you got them
 * out of the way is worse than no memory at all — and because the
 * /help-center page (HelpCenterPage.tsx) shows the same conversation.
 * `AssistantWidget` is the gate: the corner launcher and the docked panel,
 * hidden on /help-center, where the page is the open panel. `AssistantPanel`
 * is presentation plus the draft textarea, in a `dock`, `page` or `sheet` variant.
 *
 * LOOKS AND SITS LIKE INFLOWW'S OWN INTERCOM MESSENGER: a round black
 * launcher in the bottom-right corner, and above it a light panel (always
 * light, `data-look="messenger"` in app/globals.css) with a dark header that
 * fades into the body (Intercom's sizes: a 48px launcher, a 400px panel).
 * The bot chat plus an "Earlier conversations" card — no news, search, team
 * avatars or tab bar. The MoneyRail's never-dragged corner sits left of
 * the launcher to make room.
 *
 * ERRORS ARE ANSWERS. The endpoint is a 200-always contract — a used-up cap, a
 * missing agency key and a sulking provider all come back as `{answer, error}`
 * with a human sentence in `answer` — so every one of them renders as a normal
 * assistant bubble (muted when `error` is set). The bot looking broken exactly
 * when someone needs config help is the failure mode the whole endpoint exists
 * to avoid, and a red toast would reintroduce it in the last 40 lines.
 *
 * Deliberately thin: no streaming, no feedback buttons. CONVERSATIONS are
 * threads (assistantReducer.ts): every ask carries its thread id, and the
 * server's prompt context is that thread's earlier turns — the ask carries no
 * history itself, so a bare "yes" takes up the last answer's offer. Earlier
 * threads come back from the server (GET /admin/assistant/history, once per
 * page load, on the first open) and live behind the "Earlier conversations"
 * card / header button, in a list by day; picking one opens it to read or
 * continue. They are never dumped into a new chat. The header's back arrow
 * leaves a thread for a new chat.
 *
 * FOCUS — "Currently selected: …" above the composer: General (manual-only
 * answers, billed to the agency) or one model (its live state, billed to its
 * cap). It follows the app's model — the scope switcher, or a page's own
 * creator rail (Vault Pro…, contexts/PageCreatorContext.ts) while that page is open — so
 * switching model anywhere focuses the bot on it (all models → General); a
 * pick in the bot holds until the next switch. Once a conversation has started its focus is locked — the
 * server's context is per thread and account — so a switch then is only
 * offered ("<model> in app · New chat"), and picking another focus starts a
 * new chat. Any OWNED model can be the focus — an offline one (no session,
 * deactivated) is marked in the menu — and the reducer resolves every focus
 * against that roster (assistantReducer.ts, ROSTER). A chatter session cannot
 * ask without an account (the server 401s), so for one, General falls back to
 * the first account (and waits for the roster). The account in play is always
 * on screen, never inferred silently server-side.
 *
 * NO ACCOUNT AT ALL (a new agency that has connected nothing yet): General is
 * the only focus, so the request carries no `account_id` and the server
 * answers from the manual alone (service/assistant_api.py). A hint names the
 * connect path — rendered through AnswerText, so it is a link to the page
 * that does it.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef, useState, type ReactNode } from "react";
import { usePathname } from "next/navigation";
import { ArrowUp, ChevronDown, ChevronLeft, ChevronRight, History, SendHorizontal, X } from "lucide-react";

import { IfMark } from "@/components/auth/SiteLook";

import { useOptionalChatter } from "@/contexts/ChatterContext";
import { useEmployee } from "@/contexts/EmployeeContext";
import { useOptionalUser } from "@/contexts/UserContext";
import { useAppCreator } from "@/contexts/PageCreatorContext";
import { useAccounts } from "@/hooks/useAccounts";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { useDragPress } from "@/components/useDragPress";
import { relay, type AccountMeta } from "@/lib/relay";
import { cn } from "@/lib/utils";
import { lazyModule, useLazyModule } from "@/lib/lazyModule";
import { BRAND_NAME } from "@/lib/brand";
import {
  appFocusOf, assistantReducer, canGeneralOf, HISTORY_LIMIT, historyFromRows, initialAssistantState,
  sendFocusOf, settledFrom, settledFromError, threadsOf, turnsOf,
  type AskResponse, type AssistantCore, type Focus, type HistoryRow, type ThreadSummary, type Turn,
} from "./assistantReducer";
import { useBodyScrollLock } from "./useBodyScrollLock";
import { FocusLine } from "./FocusLine";
import { ThreadList } from "./ThreadList";
import {
  initialLauncherState, launcherDockReducer, launcherSpot, parseLauncherDock,
} from "./launcherDockReducer";

export type { Turn } from "./assistantReducer";

/** Open/closed survives a reload. (The conversation does too, from the server:
 *  it comes back under "Earlier".) */
const OPEN_KEY = "chatterly:assistant_open";
/** Where the phone launcher was dropped / tucked (launcherDockReducer.ts).
 *  v2: the default became tucked-left; v1 spots (often an accidental drag,
 *  since a swipe that starts on the icon moves it) are dropped so every phone
 *  starts from that default once. */
export const LAUNCHER_KEY = "chatterly:assistant_launcher_v2";

/** The Help center route: the page IS the open panel, so the corner hides there. */
export const HELP_PATH = "/help-center";

/** Mirrors `MAX_QUESTION_CHARS` in service/assistant_api.py — the server's
 *  pydantic `max_length` would 422 past it, which is the one failure the
 *  200-always contract does NOT cover. Stop it in the composer instead. */
const MAX_QUESTION_CHARS = 1000;

/** Above the composer when no account is connected. The path is the manual's
 *  own ("Connecting an OnlyFans account"), so AnswerText links it. */
const NO_ACCOUNT_HINT =
  "No account connected yet — answers come from the manual. To connect one: Creators → Manage creators → Add creator.";
/** The same for a chatter: they cannot connect one, so no path. */
const NO_ACCOUNT_CHATTER = "No creator assigned to you yet — ask your agency to share one, then ask here.";

// ── The provider ───────────────────────────────────────────────────

/** The reducer fields surfaces read (assistantReducer.ts) plus the provider's own. */
interface AssistantState extends Pick<AssistantCore, "hydrated" | "open" | "unread" | "active" | "held"> {
  toggle: () => void;
  ask: (question: string) => void;
  /** The focus asks go out with (sendFocusOf): an account id, null = General,
   *  undefined = none yet (a chatter's General while the roster loads). */
  accountId: Focus | undefined;
  /** The reducer's roster as accounts — offline ones too ([] while loading). */
  accounts: AccountMeta[];
  /** The reducer has the roster (the accounts query succeeded). */
  rosterLoaded: boolean;
  /** A signed-in user (not a chatter): the "Add creator" hint is theirs. */
  isUser: boolean;
  /** General is on offer (a signed-in user, or nothing connected). */
  canGeneral: boolean;
  /** The app switcher's focus, resolved, for the "<model> in app" offer while `held`. */
  appFocus: Focus;
  /** The open thread's turns ([] on the home screen). */
  shown: Turn[];
  /** Every conversation with a turn, newest first. */
  threads: ThreadSummary[];
  pick: (focus: Focus) => void;
  newChat: () => void;
  openThread: (t: ThreadSummary) => void;
  /** For the "Hi <name>" greeting; null falls back to "Hi there". */
  userName: string | null;
}

/** A conversation id: made here, stored by the server as-is. Not
 *  crypto.randomUUID — that needs a secure context, and a phone on the LAN
 *  testing over http has none. Unique per asker is all it needs. */
const newThreadId = () => `t${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;

const AssistantContext = createContext<AssistantState | null>(null);
const NO_ACCOUNTS: AccountMeta[] = [];

/** One conversation for both surfaces: the corner dock and the /help-center
 *  page (HelpCenterPage.tsx) read it, so a question asked on one is on the
 *  other. Mounted in app/layout.tsx inside AuthGate and PageCreatorProvider,
 *  where the app's model, roster and employee contexts resolve. */
export function AssistantProvider({ children }: { children: ReactNode }) {
  // The server doesn't know the persisted bit, so the first client render
  // must not either — read it in an effect and paint nothing until then.
  // hydrated / open / turns / unread move together: assistantReducer.ts.
  const [state, dispatch] = useReducer(assistantReducer, initialAssistantState);
  const { hydrated, open, history, turns, unread, active, held } = state;
  const pathname = usePathname();
  // A reply is "read" if the dock is open or the help page is on screen; the
  // reducer holds both and reads them when the answer lands.
  useEffect(() => { dispatch({ type: "route", onHelpPage: pathname === HELP_PATH }); }, [pathname]);
  const nextId = useRef(0);

  // OWNED accounts, a dropped session or a deactivated Creator included: the
  // server answers about any of them (its reach), and a page may pick one
  // (Vault Pro keeps a session-dropped model). The reducer resolves against
  // them. Only FETCHED data is a roster (`dataUpdatedAt` > 0: a success now or
  // before a failed refetch): a chatter's loading query carries
  // `accounts: []`, which would read as "nothing connected" (General).
  const accountsQ = useAccounts();
  const owned = accountsQ.dataUpdatedAt > 0 ? accountsQ.data?.accounts : undefined;
  const { current } = useEmployee();
  const employeeId = current?.id ?? null;
  // For the greeting only, the same name the avatar menu shows.
  const user = useOptionalUser()?.user;
  const chatter = useOptionalChatter()?.chatter;
  const userName = user?.username ?? chatter?.username ?? null;

  // The focus follows the app's model (PageCreatorContext: a page's own pick,
  // else the scope switcher; all models → General). The reducer decides
  // whether a change lands now or is only offered (a started chat). It lives
  // here, not in the panel, for the same reason `turns` does: collapsing
  // unmounts the panel.
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
      /* ignore quota / safari private */
    }
    dispatch({ type: "hydrate", open: stored });
  }, []);

  // Persist the open bit once it is known (never the pre-hydration default).
  useEffect(() => {
    if (!hydrated) return;
    try { window.localStorage.setItem(OPEN_KEY, open ? "1" : "0"); } catch {}
  }, [hydrated, open]);

  const toggle = useCallback(() => dispatch({ type: "toggle" }), []);

  // Earlier sessions' turns: once per page load, the first time a surface
  // shows the conversation. A failed read leaves it idle for the next open.
  // History is the asker's own across every account (the session decides),
  // so the read carries no account or employee header.
  const wantHistory = hydrated && (open || state.onHelpPage) && state.historyStatus === "idle";
  useEffect(() => {
    if (!wantHistory) return;
    dispatch({ type: "history_requested" });
    relay.get<{ turns: HistoryRow[] }>(`/admin/assistant/history?limit=${HISTORY_LIMIT}`)
      .then((body) => dispatch({ type: "history_loaded", turns: historyFromRows(body) }))
      .catch(() => dispatch({ type: "history_failed" }));
  }, [wantHistory]);

  const ask = useCallback(async (question: string) => {
    if (accountId === undefined) return;   // the composer is disabled meanwhile
    const id = nextId.current++;
    // The open thread, or a new one this first ask names — made here only.
    const thread = active ?? newThreadId();
    dispatch({ type: "asked", id, question, ts: new Date().toISOString(), thread, accountId });
    try {
      const r = await relay.post<AskResponse>(
        "/admin/assistant/ask",
        // No `role` — the server derives who is asking from the session, and a
        // role read out of this body would be client-supplied theater. No
        // history either: the server reads the thread's previous turns.
        // General (or no account connected) → no `account_id`: a manual-only answer.
        accountId ? { question, account_id: accountId, thread_id: thread } : { question, thread_id: thread },
        { accountId, employeeId },
      );
      dispatch(settledFrom(id, r));
    } catch (e) {
      dispatch(settledFromError(id, e));
    }
  }, [accountId, employeeId, active]);

  const pick = useCallback((focus: Focus) => dispatch({ type: "pick", focus }), []);
  const newChat = useCallback(() => dispatch({ type: "new_chat" }), []);
  const openThread = useCallback(
    (t: ThreadSummary) => dispatch({ type: "open_thread", thread: t.id, focus: t.focus }), []);

  // Stable while the conversation is unchanged: the panel's scroll-to-bottom
  // effect keys on `shown`, and a route change must not re-fire it.
  const shown = useMemo(() => turnsOf(active, history, turns), [active, history, turns]);
  const threads = useMemo(() => threadsOf(history, turns), [history, turns]);
  // The panel shows the REDUCER's roster (what sends resolve against), with
  // the query's metadata for names and offline marks.
  const rosterIds = state.roster.ids;
  const accounts = useMemo(() => {
    if (rosterIds === null) return NO_ACCOUNTS;
    const meta = new Map((owned ?? []).map((a) => [a.id, a]));
    return rosterIds.flatMap((id) => meta.get(id) ?? []);
  }, [rosterIds, owned]);
  const value: AssistantState = {
    hydrated, open, unread, active, held, toggle, ask, accountId,
    accounts, rosterLoaded: rosterIds !== null, isUser: state.roster.isUser,
    canGeneral: canGeneralOf(state.roster),
    appFocus: appFocusOf(state),
    shown, threads,
    pick, newChat, openThread, userName,
  };
  return (
    <AssistantContext.Provider value={value}>{children}</AssistantContext.Provider>
  );
}

export function useAssistant(): AssistantState {
  const v = useContext(AssistantContext);
  if (!v) throw new Error("useAssistant needs an <AssistantProvider> above it");
  return v;
}

// ── The gate ───────────────────────────────────────────────────────

export function AssistantWidget() {
  const a = useAssistant();
  const pathname = usePathname();
  const onMessagesPro = pathname === "/messages-pro" || pathname?.startsWith("/messages-pro/");
  const phone = useMediaQuery("(max-width: 767.98px)");

  if (!a.hydrated || pathname === HELP_PATH || onMessagesPro) return null;

  if (phone) {
    return (
      <>
        {a.open && <AssistantPanel variant="sheet" onClose={a.toggle} />}
        <PhoneLauncher hidden={a.open} unread={a.unread} onOpen={a.toggle} />
      </>
    );
  }

  return (
    <>
      {a.open && <AssistantPanel variant="dock" onClose={a.toggle} />}
      <button
        type="button"
        onClick={a.toggle}
        // Desktop-only (the `phone` gate above), same as the MoneyRail dock: at
        // phone widths a fixed bottom corner sits on top of the chat composer.
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
        {a.unread && !a.open && (
          <span
            className="absolute right-0 top-0 h-3 w-3 rounded-full bg-[#e5372f]"
            aria-label="New reply"
          />
        )}
      </button>
    </>
  );
}

/** The phone launcher: starts tucked into the left edge behind its chevron
 *  tab (a tap pulls the icon out). The icon drags anywhere; on release it
 *  snaps to the nearest left / right / bottom edge, or — dropped past a side
 *  edge — tucks into it behind a chevron tab that pulls it back out. A tap
 *  (no drag, useDragPress) opens the sheet. Spot and tuck persist per device
 *  under LAUNCHER_KEY. Stays mounted under the open sheet so its spot is not
 *  re-read on every close. */
function PhoneLauncher({ hidden, unread, onOpen }: { hidden: boolean; unread: boolean; onOpen: () => void }) {
  const [s, dispatch] = useReducer(launcherDockReducer, initialLauncherState);

  useEffect(() => {
    let raw: string | null = null;
    try { raw = window.localStorage.getItem(LAUNCHER_KEY); } catch { /* safari private */ }
    dispatch({ type: "load", dock: parseLauncherDock(raw), vw: window.innerWidth, vh: window.innerHeight });
    const onResize = () => dispatch({ type: "resize", vw: window.innerWidth, vh: window.innerHeight });
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  // Save after a drop or an untuck — never a drag move or the load.
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
      // Its own key, and it swallows the drag's click too: the release that
      // tucked the icon must not land here and pull it straight back out.
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
      onClick={() => { if (!swallowClick()) onOpen(); }}
      style={{ left, top }}
      // touch-none: the finger drags the icon, not the page under it.
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

/** Intercom's speech bubble with a smile, which Infloww's launcher wears. */
function LauncherIcon() {
  return (
    <svg viewBox="0 0 28 30" className="h-6 w-6" aria-hidden>
      <path d="M5 1h18a5 5 0 0 1 5 5v23l-6.5-4H5a5 5 0 0 1-5-5V6a5 5 0 0 1 5-5z" fill="currentColor" />
      <path d="M7.5 14.5c3.6 3.2 9.4 3.2 13 0" fill="none" stroke="black" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

// ── The panel ──────────────────────────────────────────────────────

/** The answer renderer (markdown + tab links, with every page's tab table behind it): out of the shell's first load,
 *  fetched when a panel opens. Plain text stands in until it lands (or if it never does). */
const answerText = lazyModule(() => import("./AnswerText"));

/** Everything that differs between the three panel variants. */
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
    // The dock sits beside the page it links to: it stays open.
    closeOnNavigate: false,
    lockPage: false,
  },
  page: {
    // `relative`: the conversations list overlays the frame.
    frame: "relative h-chat min-h-0 w-full",
    // The page spans the shell panel; its content keeps the messenger's measure.
    column: "mx-auto w-full max-w-[720px]",
    composerPad: "",
    inputText: "text-[14px]",
    closeOnNavigate: false,
    lockPage: false,
  },
  sheet: {
    // Pinned to the visual viewport (`--vvt` / `--vvh`, app/layout.tsx).
    frame: "fixed inset-x-0 top-[var(--vvt,0px)] z-50 h-[var(--vvh,100dvh)] w-full",
    column: "",
    composerPad: "pb-[max(1rem,env(safe-area-inset-bottom))]",
    // 16px on the phone: iOS zooms the page into any smaller input.
    inputText: "text-[16px]",
    // A link tapped in the full-screen sheet closes it, or the page it opened
    // stays hidden under the sheet.
    closeOnNavigate: true,
    lockPage: true,
  },
} as const;

/** The messenger's body. `dock`: Intercom's 400px panel above the launcher.
 *  `page`: the same content filling /help-center's white frame (Infloww's
 *  HelpPage: full bleed, no page header), in a centred 720px column, with no
 *  close button (the sidebar is the way out). `sheet`: the phone's full-screen
 *  messenger, pinned to the visual viewport over a locked body
 *  (useBodyScrollLock) so the keyboard never covers its composer nor scrolls
 *  the page out from under it. Earlier conversations open from a list over
 *  the panel (ThreadList), one at a time. */
export function AssistantPanel({
  variant,
  onClose,
}: {
  variant: "dock" | "page" | "sheet";
  onClose?: () => void;
}) {
  const {
    shown, threads, active, held, userName, accounts, rosterLoaded, isUser, accountId, canGeneral, appFocus,
    ask, pick, newChat, openThread,
  } = useAssistant();
  const answer = useLazyModule(answerText);
  const [draft, setDraft] = useState("");
  const [listOpen, setListOpen] = useState(false);
  const listRef = useRef<HTMLDivElement | null>(null);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);
  // An in-flight answer does NOT lock the composer: concurrent turns are fine —
  // `settled` (assistantReducer) matches answers to turns by id, never by order.
  const canSend = draft.trim().length > 0 && accountId !== undefined;
  const empty = shown.length === 0;
  const v = VARIANT[variant];
  useBodyScrollLock(v.lockPage);
  const leave = v.closeOnNavigate ? onClose : undefined;
  const column = v.column;
  const text = (body: string, muted = false) => answer
    ? <answer.AnswerText text={body} muted={muted} onNavigate={leave} />
    : <span className="whitespace-pre-wrap">{body}</span>;

  // Follow the newest row — both when a question lands and when its answer
  // replaces the "thinking…" line (which is usually the taller of the two),
  // and to the end of a conversation just opened.
  // Scrolls the list BOX, not a sentinel: scrollIntoView walks up to the
  // nearest scrollable ancestor, which on a short page is the document.
  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [shown]);

  const send = () => {
    if (!canSend) return;
    ask(draft.trim().slice(0, MAX_QUESTION_CHARS));
    setDraft("");
  };

  const renderTurn = (t: Turn) => (
    <div key={t.id} className="flex flex-col gap-2">
      <div className="self-end max-w-[85%] rounded-2xl rounded-br-md bg-[#151515] px-3.5 py-2 text-[13px] text-white whitespace-pre-wrap break-words">
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
            // A cap / missing key / provider wobble is still an answer —
            // muted, never a red error chip. See the module note.
            t.error ? "text-fg-dim" : "text-fg",
          )}
        >
          {/* The answer is markdown (the manual is), and the tab names in
              it are real destinations — AnswerText renders both with its own
              block layout; until it loads, `text` falls back to pre-wrapped
              plain text. */}
          {text(t.answer, !!t.error)}
        </div>
      )}
    </div>
  );

  return (
    <div
      data-look="messenger"
      className={cn("flex flex-col bg-panel text-fg overflow-hidden", v.frame)}
    >
      {/* Dark header fading into the light body, as Infloww's messenger. */}
      {/* Home: dark (#242424 -> #2d2d2d) down past the greeting, fading to white behind the first card,
          which overlaps it by 91px. In a conversation the header is one line and fades within itself. */}
      <div
        className={cn(
          "shrink-0 pt-[37px] text-white",
          empty
            ? "pb-[120px] bg-[linear-gradient(180deg,#242424_0%,#2d2d2d_63%,#2d2d2d_72%,#ffffff_100%)]"
            : "pb-10 bg-[linear-gradient(180deg,#242424_0%,#2d2d2d_55%,#ffffff_100%)]",
        )}
      >
        <div className={cn("px-10", column)}>
          <div className="flex h-8 items-center gap-5">
            {active !== null && (
              <button
                type="button"
                onClick={newChat}
                className="-ml-6 -mr-3 grid h-8 w-8 place-items-center rounded-md text-white hover:bg-white/10"
                title="Back — start a new chat"
                aria-label="New chat"
              >
                <ChevronLeft className="h-5 w-5" aria-hidden />
              </button>
            )}
            <IfMark className="size-7" />
            <span className="text-[18px] font-bold">{BRAND_NAME.toUpperCase()}</span>
            <span className="-mr-4 ml-auto flex items-center gap-1">
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
              Ask how something works, or paste a fan to ask why
            </p>
          )}
        </div>
      </div>

      <div ref={listRef} className={cn(empty ? "-mt-[91px]" : "-mt-6", "flex-1 min-h-0 overflow-y-auto overscroll-contain pb-3")}>
        <div className={cn("px-5 flex flex-col gap-3", column)}>
          {empty && (
            <>
              <button
                type="button"
                // preventScroll: no Safari scroll-into-view jump of the page.
                onClick={() => composerRef.current?.focus({ preventScroll: true })}
                className={cn(CARD, "flex items-center gap-4 text-left hover:border-[#dcdcdc]")}
              >
                <span className="min-w-0 flex-1">
                  <span className="block text-[15px] font-semibold text-[#14161a]">Ask a question</span>
                  <span className="block text-[15px] text-[#6d6f74]">Answers from the product manual</span>
                </span>
                <SendHorizontal className="h-5 w-5 shrink-0 fill-black text-black" aria-hidden />
              </button>
              {threads.length > 0 && (
                <button
                  type="button"
                  onClick={() => setListOpen(true)}
                  className={cn(CARD, "flex items-center gap-4 text-left hover:border-[#dcdcdc]")}
                >
                  <History className="h-[22px] w-[22px] shrink-0 text-[#14161a]" aria-hidden />
                  <span className="min-w-0 flex-1">
                    <span className="block text-[15px] font-semibold text-[#14161a]">Earlier conversations</span>
                    <span className="block text-[15px] text-[#6d6f74]">
                      {threads.length} conversation{threads.length === 1 ? "" : "s"} · last {WHEN.format(new Date(threads[0].last))}
                    </span>
                  </span>
                  <ChevronRight className="h-5 w-5 shrink-0 text-[#14161a]" aria-hidden />
                </button>
              )}
            </>
          )}
          {shown.map(renderTurn)}
        </div>
      </div>

      {/* Where Intercom's Home / News / Messages / Help bar sits: our composer. */}
      <div className="shrink-0 border-t border-[#ededed] bg-white">
        <div className={cn("px-4 pt-2.5 pb-4 flex flex-col gap-2", v.composerPad, column)}>
          {/* Both read the reducer's roster. No account at all: General is
              all there is, and for a user the one thing worth pointing at is
              where to connect one (a chatter can't: neutral copy). Nothing
              while the roster loads. */}
          {accounts.length > 0 && accountId !== undefined ? (
            <FocusLine
              focus={accountId} accounts={accounts} canGeneral={canGeneral} started={active !== null}
              held={held} appFocus={appFocus} onPick={pick} onNewChat={newChat}
            />
          ) : rosterLoaded && accounts.length === 0 && (
            <div className="px-1 text-[11px] leading-4 text-muted">{isUser ? text(NO_ACCOUNT_HINT) : NO_ACCOUNT_CHATTER}</div>
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
              placeholder="Ask a question…"
              title="Answers come from the product manual; 'not supported' is a real answer. Enter to send · Shift+Enter for a new line"
              rows={1}
              className={cn(
                "flex-1 min-w-0 max-h-28 resize-none bg-transparent py-1.5 leading-5 text-fg placeholder:text-muted focus:outline-none [field-sizing:content]",
                v.inputText,
              )}
            />
            {/* Always "Ask" — the per-turn "thinking…" row shows progress, and
                the composer stays live while an answer is in flight. */}
            <button
              type="button"
              onClick={send}
              disabled={!canSend}
              className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-[#151515] text-white transition-opacity disabled:opacity-25"
              aria-label="Ask"
              title="Send"
            >
              <ArrowUp className="h-4 w-4" aria-hidden />
            </button>
          </div>
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

const CARD = "rounded-xl border border-[#ededed] bg-white px-6 py-[17px] leading-5 shadow-[0_2px_8px_rgba(0,0,0,0.06)]";

/** Local time on the card: "Nov 10, 22:24". */
const WHEN = new Intl.DateTimeFormat("en-US", {
  month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
});
