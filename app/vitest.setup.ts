// Vitest global setup — jest-dom matchers + Next mocks so chat components render
// in jsdom. Use renderWithProviders() from ./test-utils for components that read
// the TanStack Query cache.
import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, vi } from "vitest";

import { EXIT_GHOST } from "@/hooks/layerMarks";
import { resetSendGapForTests } from "@/lib/sendGuards";

// The composer's 3 s send-rate guard is one clock for the whole window
// (lib/sendGuards): each test starts with no send behind it.
beforeEach(() => resetSendGapForTests());

// Components call usePathname/useRouter/useParams; stub them for jsdom.
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
  }),
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
  redirect: vi.fn(),
  notFound: vi.fn(),
}));

// jsdom has no Web Animations API: every animation finishes on the next
// microtask, never inside `animate()` (a browser's finishes on a later frame), so
// a sheet's settle in useSwipe ends, and calls its `onfinish`, unless cancelled first.
if (typeof HTMLElement !== "undefined") { // not in `@vitest-environment node` files
  Object.defineProperty(HTMLElement.prototype, "animate", {
    configurable: true, writable: true,
    value: () => {
      const a = { playState: "running", onfinish: null as (() => void) | null, cancel() { a.playState = "idle"; } };
      queueMicrotask(() => { if (a.playState !== "running") return; a.playState = "finished"; a.onfinish?.(); });
      return a;
    },
  });
  Object.defineProperty(HTMLElement.prototype, "getAnimations", { configurable: true, writable: true, value: () => [] });
  // A layer's leaving copy (`useExitGhost`) can sit outside the render container (a portal's parent): it goes with the test.
  afterEach(() => { for (const g of document.querySelectorAll(`.${EXIT_GHOST}`)) g.remove(); });
}
