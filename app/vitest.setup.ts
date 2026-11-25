import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, vi } from "vitest";

import { EXIT_GHOST } from "@/hooks/layerMarks";
import { resetSendGapForTests } from "@/lib/sendGuards";

beforeEach(() => resetSendGapForTests());

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

if (typeof HTMLElement !== "undefined") { // not in `@vitest-environment node` files
  // jsdom has no Web Animations API: finish on the next microtask, never inside animate() (a browser finishes on a later frame).
  Object.defineProperty(HTMLElement.prototype, "animate", {
    configurable: true, writable: true,
    value: () => {
      const a = { playState: "running", onfinish: null as (() => void) | null, cancel() { a.playState = "idle"; } };
      queueMicrotask(() => { if (a.playState !== "running") return; a.playState = "finished"; a.onfinish?.(); });
      return a;
    },
  });
  Object.defineProperty(HTMLElement.prototype, "getAnimations", { configurable: true, writable: true, value: () => [] });
  afterEach(() => { for (const g of document.querySelectorAll(`.${EXIT_GHOST}`)) g.remove(); });
}
