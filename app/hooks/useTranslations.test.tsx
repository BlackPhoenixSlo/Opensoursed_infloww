import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";

const post = vi.fn();
vi.mock("@/lib/relay", () => ({ relay: { post: (...a: unknown[]) => post(...a) } }));

import { FAILED_RETRY_MS, resetTranslationsForTests, useTranslations } from "./useTranslations";

beforeEach(() => {
  resetTranslationsForTests();
  post.mockReset();
});
afterEach(() => vi.useRealTimers());

describe("useTranslations", () => {
  it("sends the Fan's language as the hint and keeps its answers apart from unhinted ones", async () => {
    post.mockImplementation((_p: string, body: { texts: string[]; hint?: string }) =>
      Promise.resolve({ results: body.texts.map(() => ({ text: body.hint ? "Yes" : "And", lang: body.hint ?? "et" })) }));

    const hinted = renderHook(() => useTranslations(["Ja"], true, "acct-1", "de"));
    await waitFor(() => expect(hinted.result.current.get("Ja")?.text).toBe("Yes"));
    expect(post).toHaveBeenCalledWith("/admin/translate", { texts: ["Ja"], target: "en", hint: "de" }, { accountId: "acct-1" });

    const plain = renderHook(() => useTranslations(["Ja"], true, "acct-1", null));
    await waitFor(() => expect(plain.result.current.get("Ja")?.text).toBe("And"));
    expect(post).toHaveBeenLastCalledWith("/admin/translate", { texts: ["Ja"], target: "en" }, { accountId: "acct-1" });
  });

  it("keeps unhinted translations scoped to the fan", async () => {
    post.mockResolvedValueOnce({ results: [{ text: "Yes", lang: "de" }] })
      .mockResolvedValueOnce({ results: [{ text: "I", lang: "pl" }] });
    const { result, rerender } = renderHook(({ fan }) => useTranslations(["Ja"], true, "acct-1", null, fan), {
      initialProps: { fan: "fan-1" },
    });
    await waitFor(() => expect(result.current.get("Ja")?.text).toBe("Yes"));
    rerender({ fan: "fan-2" });
    await waitFor(() => expect(result.current.get("Ja")?.text).toBe("I"));
    expect(post).toHaveBeenCalledTimes(2);
  });

  it("asks again for a failed text once FAILED_RETRY_MS has passed, not before", async () => {
    const now = vi.spyOn(Date, "now").mockReturnValue(1_000_000);
    post.mockResolvedValueOnce({ results: [null] });
    const { result, rerender } = renderHook(({ texts }) => useTranslations(texts, true, "acct-1"), {
      initialProps: { texts: ["hallo"] },
    });
    await waitFor(() => expect(result.current.get("hallo")).toBeNull());
    expect(post).toHaveBeenCalledTimes(1);

    rerender({ texts: ["hallo"].slice() });
    expect(post).toHaveBeenCalledTimes(1);

    now.mockReturnValue(1_000_000 + FAILED_RETRY_MS);
    post.mockResolvedValueOnce({ results: [{ text: "hello", lang: "de" }] });
    rerender({ texts: ["hallo"].slice() });
    await waitFor(() => expect(result.current.get("hallo")?.text).toBe("hello"));
    expect(post).toHaveBeenCalledTimes(2);
    now.mockRestore();
  });
});
