/**
 * UltraPlanPage — the card shows each send's FULL text and rows from the server, the one OK posts the shown hash,
 * a 404 is a plain line, and an uncertain end says so.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import UltraPlanPage from "@/components/ultra/UltraPlanPage";
import { RelayError } from "@/lib/relay";
import type { PlanView } from "./ultraRunReducer";

const LONG = "one driink for halloween " + "x".repeat(1500);
const view = (over: Partial<PlanView> = {}): PlanView => ({
  id: "p1", status: "awaiting_ok", summary: "Halloween push", sha256: "b".repeat(64),
  card: [
    { id: "folder", tool: "of_folder_create", effect: "write", title: "OF Folder Create", rows: [["Creator", "Ava"], ["name", "Halloween"]] },
    { id: "mass", tool: "mass_send", effect: "send", title: "Mass message", text: LONG,
      rows: [["Creator", "Ava"], ["Audience", "lists fans"], ["Price", "$12.00"], ["Media", "1"], ["When", "now"]] },
  ],
  step_states: [{ id: "folder", state: "pending" }, { id: "mass", state: "pending" }],
  created_at: "", expires_at: "", approved_at: null, finished_at: null, ...over,
});

const gets: string[] = [];
const posts: [string, unknown][] = [];
let getImpl: () => Promise<PlanView> = async () => view();
let postImpl: () => Promise<PlanView> = async () => view({ status: "running" });
vi.mock("@/lib/relay", async (orig) => ({
  ...(await orig<typeof import("@/lib/relay")>()),
  relay: {
    get: (p: string) => { gets.push(p); return getImpl(); },
    post: (p: string, b: unknown) => { posts.push([p, b]); return postImpl(); },
  },
}));

afterEach(() => {
  cleanup();
  gets.length = 0;
  posts.length = 0;
  getImpl = async () => view();
  postImpl = async () => view({ status: "running" });
});

describe("UltraPlanPage", () => {
  it("a done send shows the OnlyFans id it made", async () => {
    getImpl = async () => view({
      status: "done",
      step_states: [{ id: "folder", state: "done" }, { id: "mass", state: "done", result: { id: 4242 } }],
    });
    render(<UltraPlanPage planId="p1" />);
    await screen.findByRole("status");
    expect(document.querySelector('[data-step="mass"]')).toHaveTextContent("OnlyFans id: 4242");
  });

  it("a done mass that skipped fans says how many went out", async () => {
    const note = "sent to 1 of 2 fans by id: 1 skipped (opted out or already queued)";
    getImpl = async () => view({
      status: "done",
      step_states: [{ id: "folder", state: "done" }, { id: "mass", state: "done", result: { id: 4242 }, note }],
    });
    render(<UltraPlanPage planId="p1" />);
    await screen.findByRole("status");
    expect(document.querySelector('[data-step="mass"] [data-step-note]')).toHaveTextContent(note);
  });

  it("shows every step with the send's full text and rows, and OK posts the shown hash", async () => {
    render(<UltraPlanPage planId="p1" />);
    expect((await screen.findByText(LONG)).hasAttribute("data-step-text")).toBe(true);
    for (const v of ["lists fans", "$12.00", "Halloween"]) expect(screen.getByText(v)).toBeInTheDocument();
    expect(document.querySelector('[data-step="folder"] h3')).toHaveTextContent("1. OF Folder Create");
    expect(document.querySelector('[data-step="mass"] h3')).toHaveTextContent("2. Mass message");
    expect(gets).toEqual(["/admin/ultra/plans/p1"]);
    fireEvent.click(screen.getByRole("button", { name: "OK, run 2 steps" }));
    await vi.waitFor(() => expect(document.querySelector("[data-plan-status]")?.getAttribute("data-plan-status")).toBe("running"));
    expect(posts).toEqual([["/admin/ultra/plans/p1/ok", { sha256: "b".repeat(64) }]]);
    expect(screen.queryByRole("button", { name: /^OK/ })).toBeNull();
    expect(screen.getByRole("button", { name: "Cancel the rest" })).toBeEnabled();
  });

  it("a refused OK shows the Relay's words", async () => {
    postImpl = async () => { throw new RelayError(409, {}, "plan expired"); };
    render(<UltraPlanPage planId="p1" />);
    fireEvent.click(await screen.findByRole("button", { name: "OK, run 2 steps" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("plan expired");
  });

  it("a 404 is a plain line, no plan", async () => {
    getImpl = async () => { throw new RelayError(404, {}, "plan not found"); };
    render(<UltraPlanPage planId="p1" />);
    expect(await screen.findByText("No such plan, or it is not one of yours.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^OK/ })).toBeNull();
  });

  it("an uncertain send says to check OnlyFans, with no buttons", async () => {
    getImpl = async () => view({
      status: "failed",
      step_states: [{ id: "folder", state: "done", open_url: "/growth/vault-pro", result: { id: 7001 } },
        { id: "mass", state: "uncertain", error: "no answer from the relay", open_url: "/growth/smart-messages" }],
    });
    render(<UltraPlanPage planId="p1" />);
    expect(await screen.findByRole("status")).toHaveTextContent("Check OnlyFans before sending it again.");
    expect(screen.getByText("no answer from the relay")).toBeInTheDocument();
    expect(document.querySelector('[data-step="folder"]')).toHaveTextContent("Id: 7001");
    expect(screen.getAllByRole("link", { name: "Open in the app" }).map((a) => a.getAttribute("href")))
      .toEqual(["/growth/vault-pro", "/growth/smart-messages"]);
    expect(screen.queryByRole("button")).toBeNull();
    expect(document.querySelector("ol")?.className).not.toContain("safe-area");
  });

  it("the step list is padded by the sticky bar's height, phone safe-area included", async () => {
    render(<UltraPlanPage planId="p1" />);
    await screen.findByRole("button", { name: "OK, run 2 steps" });
    expect(document.querySelector("ol")?.className).toContain("pb-[calc(105px+env(safe-area-inset-bottom))]");
    expect(document.querySelector("ol")?.className).toContain("sm:pb-[calc(61px+env(safe-area-inset-bottom))]");
    fireEvent.click(screen.getByRole("button", { name: "OK, run 2 steps" }));
    await vi.waitFor(() => expect(document.querySelector("[data-plan-status]")?.getAttribute("data-plan-status")).toBe("running"));
    expect(document.querySelector("ol")?.className).toContain("pb-[calc(61px+env(safe-area-inset-bottom))]");
    expect(document.querySelector("ol")?.className).not.toContain("105px");
  });
});
