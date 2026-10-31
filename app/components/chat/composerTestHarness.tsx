/**
 * Seam 1 of docs/spec/phase-04-composer-ppv-vault.md: the one render helper
 * the Phase's Composer suites share (`PpvRow.test.tsx`,
 * `ComposerToolbar.test.tsx` and `TimedMessagePopover.test.tsx`).
 *
 * The Composer renders through the house provider wrapper
 * (`renderWithProviders`). `@/lib/relay` is mocked by URL so the real hooks
 * run, and the `VaultPicker` module is replaced by a stub dialog whose button
 * confirms fixture media. vi.mock is hoisted per test file, so each suite
 * declares the two mocks itself and points them at this module:
 *
 *   vi.mock("@/lib/relay", async (orig) =>
 *     (await import("./composerTestHarness")).mockRelayModule(await orig()));
 *   vi.mock("./VaultPicker", async () =>
 *     (await import("./composerTestHarness")).vaultPickerStubModule);
 *
 * `Composer` is imported lazily inside `renderComposer` so this module never
 * imports `@/lib/relay` while that mock factory is importing it.
 *
 * Seam 2 (`VaultPicker.test.tsx`) and Phase 2's `FanList.test.tsx` reuse the
 * relay mock, `routeRelay` and `observerStub`; `FanList.test.tsx` also takes
 * the events mock, so the real `useInboxRealtime` hears what a case emits.
 */
import { expect, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import type { UserEvent } from "@testing-library/user-event";

import type * as RelayModule from "@/lib/relay";
import type { RelayContext, VaultMedia } from "@/lib/relay";
import { resetSendGapForTests } from "@/lib/sendGuards";
import { renderWithProviders } from "@/test-utils";
import type { ComposerApi, ComposerProps, SendArgs } from "./Composer";
import { clearRefusedOffers } from "./refusedOffers";

/* ── relay, mocked by URL ───────────────────────────────────────────────── */

/** A route's reply, from the path and the context the request was made with
 *  (its Creator in `ctx.accountId`). */
type Route = (path: string, ctx?: RelayContext) => unknown;

/** Extra routes a suite registers for one test, checked before the defaults.
 *  Cleared by `resetComposerHarness`. */
const routes: Array<{ match: string; reply: Route }> = [];

export function routeRelay(match: string, reply: Route) {
  routes.push({ match, reply });
}

// Replies are `Promise<any>` so the mock satisfies the real generic
// `relay.get<T>` / `relay.post<T>` signatures (see `mockRelayModule`).
// `relayGet` takes the real client's arguments, so a case can read the
// context a request was made with (`mock.calls[i][1]?.accountId`).
export const relayGet = vi.fn((
  path: string, _ctx?: RelayContext, _signal?: AbortSignal, _opts?: { refresh?: boolean },
): Promise<any> => {
  const hit = routes.find((r) => path.includes(r.match));
  if (hit) return Promise.resolve(hit.reply(path, _ctx));
  if (path.includes("/admin/vault/fan-history")) return Promise.resolve({ by_media: {} });
  if (path.includes("/admin/saved-replies")) return Promise.resolve({ list: [] });
  if (path.includes("/messages/templates")) return Promise.resolve([]);
  if (path.includes("/posts/tagged-friend-users")) return Promise.resolve({ items: [], hasMore: false });
  if (path.includes("/giphy/proxy/gifs/")) return Promise.resolve({ data: [] });
  return Promise.resolve({});
});
export const relayPost = vi.fn((_path: string, _body?: unknown, _ctx?: RelayContext): Promise<any> => Promise.resolve({}));

/** The mocked `@/lib/relay`: the real module with `relay` swapped for the
 *  URL-routed mock. `satisfies typeof actual.relay` keeps the mock's methods
 *  in step with the real client under tsc. The GIF helpers are re-pointed at the mock with the same
 *  paths they request today, because the real ones close over the real
 *  `relay`. */
export function mockRelayModule(actual: typeof RelayModule) {
  return {
    ...actual,
    relay: {
      get: relayGet,
      post: relayPost,
      put: vi.fn(),
      patch: vi.fn(),
      delete: vi.fn(),
      uploadFile: vi.fn(),
      uploadForm: vi.fn(),
    } satisfies typeof actual.relay,
    gifTrending: (limit = 20, offset = 0) =>
      relayGet(`/api/of/v2/giphy/proxy/gifs/trending?${new URLSearchParams({
        limit: String(limit), offset: String(offset),
      })}`),
    gifSearch: (q: string, limit = 20, offset = 0) =>
      relayGet(`/api/of/v2/giphy/proxy/gifs/search?${new URLSearchParams({
        q, limit: String(limit), offset: String(offset),
      })}`),
  };
}

/** jsdom has no IntersectionObserver; an infinite-scroll sentinel (the Vault
 *  picker's, the Fan List's) constructs one on mount. Install it with
 *  `vi.stubGlobal("IntersectionObserver", observerStub)`. */
export const observerStub = vi.fn(function () {
  return { observe: vi.fn(), unobserve: vi.fn(), disconnect: vi.fn() };
});

/* ── the realtime event bus, mocked ────────────────────────────────────── */

type EventHandler = (env: unknown, rawType?: string) => void;
/** The handlers subscribed through the mocked `eventBus.on`, by event type.
 *  Cleared by `resetComposerHarness`. */
const eventHandlers = new Map<string, Set<EventHandler>>();

/** The mocked `@/lib/events`, shaped as `hooks/useChatList.test.tsx:53-65`
 *  mocks it: `eventBus.on` subscribes and returns its unsubscriber.
 *
 *   vi.mock("@/lib/events", async () =>
 *     (await import("./composerTestHarness")).mockEventsModule());
 */
export function mockEventsModule() {
  return {
    eventBus: {
      on(type: string, fn: EventHandler) {
        let set = eventHandlers.get(type);
        if (!set) { set = new Set(); eventHandlers.set(type, set); }
        set.add(fn);
        return () => set.delete(fn);
      },
      isConnected: () => false,
      isPaused: () => false,
      onStateChange: () => () => {},
    },
  };
}

/** Deliver one event envelope to its type's subscribers, as the SSE bus
 *  does. Wrap the call in `act`. */
export function emitEvent(type: string, env: unknown) {
  eventHandlers.get(type)?.forEach((fn) => fn(env, type));
}

/* ── VaultPicker, stubbed ───────────────────────────────────────────────── */

/** Synthetic vault media with suggested prices $10 and $25, in pick order.
 *  The pick order is deliberately sorted by neither id nor price (9102/$10
 *  before 9101/$25), so a Composer that reorders attachments fails the pins. */
export const FIXTURE_MEDIA: VaultMedia[] = [
  { id: 9102, type: "photo", _ai: { suggested_price_cents: 1000 } },
  { id: 9101, type: "video", _ai: { suggested_price_cents: 2500 } },
];

function VaultPickerStub({
  onConfirm, onClose,
}: { onConfirm: (picked: VaultMedia[]) => void; onClose: () => void }) {
  return (
    <div role="dialog" aria-label="Vault picker stub">
      <button
        type="button"
        onClick={() => {
          onConfirm(FIXTURE_MEDIA);
          onClose();
        }}
      >
        Confirm fixture media
      </button>
    </div>
  );
}

export const vaultPickerStubModule = { VaultPicker: VaultPickerStub };

/* ── render ─────────────────────────────────────────────────────────────── */

export function resetComposerHarness() {
  routes.length = 0;
  eventHandlers.clear();
  relayGet.mockClear();
  relayPost.mockClear();
  localStorage.clear();
  sessionStorage.clear(); // a chat's composer draft (lib/chatDrafts)
  resetSendGapForTests(); // the send-rate guard: one clock per model, shared by its composers
  clearRefusedOffers(); // refused schedules outlive a Composer (./refusedOffers)
}

/** The Fan a suite's Composer is for unless it names one (ChatSurface
 *  always has its Fan). */
export const HARNESS_FAN = 500;

/** Render the Composer as the chat surface does. Returns RTL utils, the
 *  `onSend` spy (what each send puts on the wire) and the API ref. */
export async function renderComposer(props: Partial<ComposerProps> = {}) {
  const { Composer } = await import("./Composer");
  const onSend = vi.fn<(args: SendArgs) => Promise<void>>(() => Promise.resolve());
  const api: React.MutableRefObject<ComposerApi | null> = { current: null };
  const utils = renderWithProviders(
    <Composer accountId="acct-1" fanId={HARNESS_FAN} onSend={onSend} composerApiRef={api} {...props} />,
  );
  return { ...utils, onSend, api };
}

/** Open ⏱ and click its "Send at" preset `+<minutes>m` (TODO.md A2: they
 *  moved there from the "+" Extras overflow). */
export async function pickSendAt(user: UserEvent, minutes: number) {
  await user.click(
    within(screen.getByRole("toolbar", { name: "Composer buttons" }))
      .getByRole("button", { name: "Timed message" }),
  );
  const presets = within(screen.getByRole("group", { name: "Send at presets" }));
  await user.click(presets.getByRole("button", { name: `+${minutes}m` }));
}

/** The tooltip a browser shows for `el`: its own title, else the nearest
 *  titled ancestor's. */
export function tooltipOf(el: HTMLElement): string | null {
  return el.closest("[title]")?.getAttribute("title") ?? null;
}

/** Asserts each element comes after the one before it in the document. */
export function expectDomOrder(elements: HTMLElement[]) {
  for (let i = 1; i < elements.length; i++) {
    expect(
      elements[i - 1].compareDocumentPosition(elements[i]) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  }
}
