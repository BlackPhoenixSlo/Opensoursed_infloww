// Vitest global setup — jest-dom matchers + Next mocks so chat components render
// in jsdom. Use renderWithProviders() from ./test-utils for components that read
// the TanStack Query cache.
import "@testing-library/jest-dom/vitest";
import { beforeEach, vi } from "vitest";

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
