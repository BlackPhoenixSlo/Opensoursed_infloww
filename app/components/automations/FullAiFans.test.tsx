/**
 * Full AI Chat's "Who Full AI answers when Live": the Fans row and dialog. The top "Fans & Following" row only reads the
 * pick: Include while no list is included, Neither once one is; picking Include there clears the includes (excludes
 * stay). Save goes to the audience write (`putAudience`), Live or not; a D61 refusal shows inside the dialog with Turn
 * Off and save (Mode Off, then the same save) / Cancel; any other failure shows above Save.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";

vi.mock("@/components/audience/fanLists", () => ({
  useFanLists: () => ({ isLoading: false, data: {}, customLists: [{ id: 11, name: "VIP", usersCount: 4 }, { id: 12, name: "Timewasters" }] }),
}));
const mode = vi.hoisted(() => ({ now: "off" as string, setOff: vi.fn() }));
vi.mock("@/hooks/useFullAiMode", () => ({
  useFullAiMode: () => ({ data: { mode: mode.now, off_switch: false, blockers: [] } }),
  useSetFullAiMode: () => ({ mutateAsync: mode.setOff }),
}));

import { FansRow } from "@/components/automations/FullAiFans";
import type { FullAiConfig } from "@/components/automations/fullAiConfig";
import type { AudienceResult } from "@/components/automations/fullAiTestChat";
import type { FullAiConfigApi } from "@/hooks/useFullAiConfig";
import { LIVE_NO_LIST } from "@/components/automations/fansForm";

beforeEach(() => {
  mode.now = "off";
  mode.setOff.mockReset();
  mode.setOff.mockResolvedValue({ mode: "off", off_switch: false, blockers: [] });
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
  it("one line: the stored value; no Live warning while Off", () => {
    render(<FansRow accountId="1" stored={{ fans: { include: [11], exclude: [] } } as FullAiConfig} cfg={{} as FullAiConfigApi} />);
    expect(screen.getByText("1 included")).toBeTruthy();
    expect(screen.queryByText(LIVE_NO_LIST)).toBeNull();
  });

  it("Live with no list: the row and the dialog give the server's D61 sentence", () => {
    mode.now = "live";
    open({ include: [], exclude: [] });
    expect(screen.getAllByText(LIVE_NO_LIST)).toHaveLength(2);
  });

  it("Live: Save goes to the audience write at once (never the draft)", async () => {
    mode.now = "live";
    const { putAudience, radio } = open({ include: [11], exclude: [] });
    expect(screen.getByText(/changes who Full AI answers right now/)).toBeTruthy();
    fireEvent.click(radio("Timewasters", "Exclude"));
    await save();
    expect(putAudience).toHaveBeenCalledWith({ fans: { include: [11], exclude: [12] } });
    expect(mode.setOff).not.toHaveBeenCalled();
  });

  it("D61 refusal: a popup in the dialog with the server's words; Cancel keeps the dialog and the pick", async () => {
    mode.now = "live";
    const reason = "Live needs a Fans list: keep an include or exclude list, or set Off first.";
    const { putAudience, radio, on } = open({ include: [11], exclude: [] }, [{ kind: "needsOff", reason }]);
    fireEvent.click(radio("VIP", "Neither"));
    await save();
    const pop = within(screen.getByRole("alertdialog", { name: "Save refused" }));
    expect(pop.getByText(reason)).toBeTruthy();
    expect(screen.queryByText("Someone saved this config meanwhile. Reload.")).toBeNull();
    fireEvent.click(pop.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(screen.getByRole("dialog", { name: "Fans" })).toBeTruthy();
    expect(on("VIP", "Neither")).toBe(true);
    expect(putAudience).toHaveBeenCalledTimes(1);
  });

  it("Turn Off and save: Mode Off first, then the same save; the dialog closes", async () => {
    mode.now = "live";
    const order: string[] = [];
    mode.setOff.mockImplementation(async (m: string) => { order.push(`mode ${m}`); return { mode: "off" }; });
    const { putAudience, radio } = open({ include: [11], exclude: [] }, [{ kind: "needsOff", reason: "Live needs a Fans list" }]);
    putAudience.mockImplementation(async (p: unknown): Promise<AudienceResult> => {
      order.push(`fans ${JSON.stringify(p)}`);
      return order.length === 1 ? { kind: "needsOff", reason: "Live needs a Fans list" } : { kind: "ok" };
    });
    fireEvent.click(radio("VIP", "Neither"));
    await save();
    await save("Turn Off and save");
    const fans = JSON.stringify({ fans: { include: [], exclude: [] } });
    expect(order).toEqual([`fans ${fans}`, "mode off", `fans ${fans}`]);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("another failure shows above Save inside the dialog", async () => {
    open({ include: [], exclude: [] }, [{ kind: "failed", reason: "fans: bad id 0 in include" }]);
    await save();
    expect(within(screen.getByRole("dialog", { name: "Fans" })).getByText("fans: bad id 0 in include")).toBeTruthy();
  });
});
