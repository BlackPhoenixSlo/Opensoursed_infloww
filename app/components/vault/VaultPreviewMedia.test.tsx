import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";

import VaultPreviewMedia from "./VaultPreviewMedia";
import { type VaultMedia } from "@/lib/relay";

const video = (id: number, url: string) =>
  ({ id, type: "video", files: { full: { url } } }) as unknown as VaultMedia;

function mount(m: VaultMedia) {
  return render(<VaultPreviewMedia media={m} accountId="acc" onExpand={() => {}} />);
}
const player = (c: HTMLElement) => c.querySelector("video") as HTMLVideoElement;

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("the inline video's loading circle", () => {
  it("hides the player behind the circle until it can play, then 500ms more", () => {
    vi.useFakeTimers();
    const { container } = mount(video(1, "https://cdn.example/a.mp4"));
    expect(screen.getByRole("status", { name: "Loading video" })).toBeTruthy();
    expect(player(container).className).toContain("invisible");

    fireEvent.loadedData(player(container));
    act(() => vi.advanceTimersByTime(499));
    expect(screen.queryByRole("status", { name: "Loading video" })).not.toBeNull();
    act(() => vi.advanceTimersByTime(1));
    expect(screen.queryByRole("status", { name: "Loading video" })).toBeNull();
    expect(player(container).className).not.toContain("invisible");
  });

  it("starts over when the selection changes", () => {
    vi.useFakeTimers();
    const { container, rerender } = mount(video(1, "https://cdn.example/a.mp4"));
    fireEvent.canPlay(player(container));
    act(() => vi.advanceTimersByTime(500));
    expect(screen.queryByRole("status", { name: "Loading video" })).toBeNull();

    rerender(<VaultPreviewMedia media={video(2, "https://cdn.example/b.mp4")} accountId="acc" onExpand={() => {}} />);
    expect(screen.getByRole("status", { name: "Loading video" })).toBeTruthy();
  });

  it("stops spinning and says so on an error", () => {
    const { container } = mount(video(1, "https://cdn.example/a.mp4"));
    fireEvent.error(player(container));
    expect(screen.queryByRole("status", { name: "Loading video" })).toBeNull();
    expect(screen.getByRole("alert").textContent).toMatch(/Couldn.t load this video/);
  });

  it("does not spin forever", () => {
    vi.useFakeTimers();
    const { container } = mount(video(1, "https://cdn.example/a.mp4"));
    act(() => vi.advanceTimersByTime(15_000));
    expect(screen.queryByRole("status", { name: "Loading video" })).toBeNull();
    expect(player(container).className).not.toContain("invisible");
  });
});
