// vi.mock is hoisted per test file, so each suite declares the relay and VaultPicker mocks itself.
// Composer is imported lazily in renderComposer so this module never imports @/lib/relay while that mock factory is importing it.
import { expect, onTestFinished, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import type { UserEvent } from "@testing-library/user-event";
import type { QueryClient } from "@tanstack/react-query";

import type * as RelayModule from "@/lib/relay";
import type { RelayContext, VaultMedia } from "@/lib/relay";
import { resetSendGapForTests } from "@/lib/sendGuards";
import { renderWithProviders } from "@/test-utils";
import type { ComposerApi, ComposerProps, SendArgs } from "./Composer";
import { clearRefusedOffers } from "./refusedOffers";


type Route = (path: string, ctx?: RelayContext) => unknown;

const routes: Array<{ match: string; reply: Route }> = [];

export function routeRelay(match: string, reply: Route) {
  routes.push({ match, reply });
}

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

export const observerStub = vi.fn(function () {
  return { observe: vi.fn(), unobserve: vi.fn(), disconnect: vi.fn() };
});


type EventHandler = (env: unknown, rawType?: string) => void;
const eventHandlers = new Map<string, Set<EventHandler>>();

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

export function streamUp(bus: { onStateChange(fn: (up: boolean) => void): () => void }): void {
  const spy = vi.spyOn(bus, "onStateChange").mockImplementation((fn) => { fn(true); return () => {}; });
  onTestFinished(() => spy.mockRestore());
}

export function emitEvent(type: string, env: unknown) {
  eventHandlers.get(type)?.forEach((fn) => fn(env, type));
}


// Pick order is deliberately sorted by neither id nor price, so a Composer that reorders attachments fails the pins.
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


export function resetComposerHarness() {
  routes.length = 0;
  eventHandlers.clear();
  relayGet.mockClear();
  relayPost.mockClear();
  localStorage.clear();
  sessionStorage.clear();
  resetSendGapForTests();
  clearRefusedOffers();
}

export const HARNESS_FAN = 500;

export async function renderComposer(props: Partial<ComposerProps> = {}, client?: QueryClient) {
  const { Composer } = await import("./Composer");
  const onSend = vi.fn<(args: SendArgs) => Promise<void>>(() => Promise.resolve());
  const api: React.MutableRefObject<ComposerApi | null> = { current: null };
  const utils = renderWithProviders(
    <Composer accountId="acct-1" fanId={HARNESS_FAN} onSend={onSend} composerApiRef={api} {...props} />,
    client,
  );
  return { ...utils, onSend, api };
}

export async function pickSendAt(user: UserEvent, minutes: number) {
  await user.click(
    within(screen.getByRole("toolbar", { name: "Composer buttons" }))
      .getByRole("button", { name: "Timed message" }),
  );
  const presets = within(screen.getByRole("group", { name: "Send at presets" }));
  await user.click(presets.getByRole("button", { name: `+${minutes}m` }));
}

export function tooltipOf(el: HTMLElement): string | null {
  return el.closest("[title]")?.getAttribute("title") ?? null;
}

export function expectDomOrder(elements: HTMLElement[]) {
  for (let i = 1; i < elements.length; i++) {
    expect(
      elements[i - 1].compareDocumentPosition(elements[i]) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  }
}
