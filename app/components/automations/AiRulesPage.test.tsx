/** AI rules page: cards render from GET /admin/full-ai/rules, a click opens the drawer with the full prompt, the
 *  no Test|Shadow toggle. */
import { afterEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";

vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return { ...mod, relay: { ...mod.relay, get: vi.fn(), put: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } };
});

import AiRulesPage from "@/components/automations/AiRulesPage";
import { relay } from "@/lib/relay";
import type { Rules } from "./aiRulesView";

const relayGet = relay.get as unknown as Mock;
const PROMPT = "Is he asking to buy something right now?\nAnswer from his newest lines only.";

const rules = (mode: "test" | "shadow"): Rules => ({
  mode,
  versions: { question_version: "abc123" },
  nodes: [
    { id: "his_lines", title: "His lines + state", group: "input", summary: "What the Router reads.", flags: [], blocks: [] },
    {
      id: "router_jev", title: mode === "test" ? "Router Jev" : "Router Jev (shadow)", group: "jev",
      summary: "One Jev call answers every question.",
      flags: [{ key: "sext_scene", label: "Sext scene", default: true }],
      blocks: [{ label: "promo (Noul)", kind: "prompt", source: "service/automations/_router_jev.py:QUESTIONS", text: PROMPT, qid: "promo" }],
    },
  ],
  edges: [{ from: "his_lines", to: "router_jev", label: "state" }],
});

afterEach(() => { cleanup(); relayGet.mockReset(); });

describe("AiRulesPage", () => {
  it("renders cards, opens the drawer with the prompt, and refetches on Mode", async () => {
    relayGet.mockImplementation((url: string) => Promise.resolve(rules(url.endsWith("shadow") ? "shadow" : "test")));
    render(<AiRulesPage />);

    expect(await screen.findByRole("button", { name: "Router Jev" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "His lines + state" })).toBeTruthy();
    expect(relayGet).toHaveBeenCalledWith("/admin/full-ai/rules?mode=test", expect.anything());
    expect(screen.getByText("state")).toBeTruthy(); // edge label

    fireEvent.click(screen.getByRole("button", { name: "Router Jev" }));
    const drawer = await screen.findByRole("dialog", { name: "Router Jev" });
    const pre = within(drawer).getByText((_, el) => el?.tagName === "PRE" && el.textContent === PROMPT);
    expect(pre).toBeTruthy();
    expect(within(drawer).getByText("service/automations/_router_jev.py:QUESTIONS")).toBeTruthy();

    fireEvent.click(within(drawer).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();

    expect(screen.queryByRole("button", { name: "Shadow" })).toBeNull();
  });

  it("shows the read's error", async () => {
    relayGet.mockRejectedValue(new Error("401 sign in"));
    render(<AiRulesPage />);
    expect(await screen.findByText("401 sign in")).toBeTruthy();
  });
});
