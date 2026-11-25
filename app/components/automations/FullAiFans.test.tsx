import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";

vi.mock("@/components/audience/fanLists", () => ({
  useFanLists: () => ({ isLoading: false, data: {}, customLists: [{ id: 11, name: "VIP", usersCount: 4 }, { id: 12, name: "Timewasters" }] }),
}));
const mode = vi.hoisted(() => ({ now: "off" as string }));
vi.mock("@/hooks/useFullAiMode", () => ({
  useFullAiMode: () => ({ data: { mode: mode.now, off_switch: false, blockers: [] } }),
}));

import { FansRow } from "@/components/automations/FullAiFans";
import type { FullAiConfig } from "@/components/automations/fullAiConfig";
import type { AudienceResult } from "@/components/automations/fullAiTestChat";
import type { FullAiConfigApi } from "@/hooks/useFullAiConfig";

beforeEach(() => {
  mode.now = "off";
});
afterEach(cleanup);

const open = (fans: { include: number[]; exclude: number[] }, answers: AudienceResult[] = [{ kind: "ok" }]) => {
  const putAudience = vi.fn(async (_p: unknown): Promise<AudienceResult> => answers.shift() ?? { kind: "ok" });
  render(<FansRow accountId="1" stored={{ fans } as FullAiConfig} cfg={{ putAudience } as unknown as FullAiConfigApi} />);
  fireEvent.click(screen.getByRole("button", { name: "Choose fans" }));
  const radio = (group: string, name: string) => within(screen.getByRole("radiogroup", { name: group })).getByRole("radio", { name });
  const on = (group: string, name: string) => radio(group, name).getAttribute("aria-checked") === "true";
  return { putAudience, radio, on };
};
const save = async (name = "Save") => { await act(async () => { fireEvent.click(screen.getByRole("button", { name })); }); };

describe("Fans dialog · Fans & Following row", () => {
  it("has two options and reads Include while no list is included", () => {
    const { on } = open({ include: [], exclude: [] });
    expect(within(screen.getByRole("radiogroup", { name: "Fans & Following" })).getAllByRole("radio")).toHaveLength(2);
    expect(on("Fans & Following", "Include")).toBe(true);
  });

  it("swaps to Neither when a list is included, back to Include when it returns to Neither", () => {
    const { radio, on } = open({ include: [], exclude: [] });
    fireEvent.click(radio("VIP", "Include"));
    expect(on("Fans & Following", "Neither")).toBe(true);
    fireEvent.click(radio("VIP", "Neither"));
    expect(on("Fans & Following", "Include")).toBe(true);
  });

  it("an excluded list leaves it on Include", () => {
    const { radio, on } = open({ include: [], exclude: [] });
    fireEvent.click(radio("Timewasters", "Exclude"));
    expect(on("Fans & Following", "Include")).toBe(true);
  });

  it("picking Include clears the included lists, keeps excludes, and Save stores lists only", async () => {
    const { putAudience, radio, on } = open({ include: [11], exclude: [12] });
    expect(on("Fans & Following", "Neither")).toBe(true);
    fireEvent.click(radio("Fans & Following", "Include"));
    expect(on("VIP", "Neither")).toBe(true);
    expect(on("Timewasters", "Exclude")).toBe(true);
    await save();
    expect(putAudience).toHaveBeenCalledWith({ fans: { include: [], exclude: [12] } });
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("Fans row and Save", () => {
  it("one line: the stored value", () => {
    render(<FansRow accountId="1" stored={{ fans: { include: [11], exclude: [] } } as FullAiConfig} cfg={{} as FullAiConfigApi} />);
    expect(screen.getByText("1 included")).toBeTruthy();
  });

  it("Live with no list: reads Every Fan, no warning; Save of no list goes through and closes", async () => {
    mode.now = "live";
    const { putAudience, radio } = open({ include: [11], exclude: [] });
    fireEvent.click(radio("VIP", "Neither"));
    await save();
    expect(putAudience).toHaveBeenCalledWith({ fans: { include: [], exclude: [] } });
    expect(screen.queryByRole("dialog")).toBeNull();
    cleanup();
    render(<FansRow accountId="1" stored={{ fans: { include: [], exclude: [] } } as FullAiConfig} cfg={{} as FullAiConfigApi} />);
    expect(screen.getByText("Every Fan")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("Live: Save goes to the audience write at once (never the draft)", async () => {
    mode.now = "live";
    const { putAudience, radio } = open({ include: [11], exclude: [] });
    expect(screen.getByText(/changes who Full AI answers right now/)).toBeTruthy();
    fireEvent.click(radio("Timewasters", "Exclude"));
    await save();
    expect(putAudience).toHaveBeenCalledWith({ fans: { include: [11], exclude: [12] } });
  });

  it("another failure shows above Save inside the dialog", async () => {
    open({ include: [], exclude: [] }, [{ kind: "failed", reason: "fans: bad id 0 in include" }]);
    await save();
    expect(within(screen.getByRole("dialog", { name: "Fans" })).getByText("fans: bad id 0 in include")).toBeTruthy();
  });
});
