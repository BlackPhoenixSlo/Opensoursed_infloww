import { afterEach, describe, expect, it, vi } from "vitest";

/** lib/brand.ts reads NEXT_PUBLIC_BRAND_* at import (Next inlines them at build), so each case imports it fresh. */
async function load(env: Record<string, string>) {
  vi.resetModules();
  for (const [k, v] of Object.entries(env)) vi.stubEnv(k, v);
  return import("@/lib/brand");
}

afterEach(() => vi.unstubAllEnvs());

describe("brand", () => {
  it("defaults to Inflowwww, no logo, and the OIF favicon", async () => {
    const b = await load({ NEXT_PUBLIC_BRAND_NAME: "", NEXT_PUBLIC_BRAND_LOGO: "" });
    expect(b.BRAND_NAME).toBe("Inflowwww");
    expect(b.BRAND_LOGO).toBe("");
    expect(b.BRAND_ICONS).toEqual({ icon: { url: "/icon.svg", type: "image/svg+xml", sizes: "any" } });
  });

  it("the env renames the product and points the mark and favicons at its logo", async () => {
    const b = await load({ NEXT_PUBLIC_BRAND_NAME: "Acme Desk", NEXT_PUBLIC_BRAND_LOGO: "/acme/logo" });
    expect(b.BRAND_NAME).toBe("Acme Desk");
    expect(b.BRAND_LOGO).toBe("/acme/logo");
    expect(b.BRAND_ICONS).toEqual({
      icon: { url: "/acme/logo-32.png", type: "image/png", sizes: "32x32" },
      apple: "/acme/logo-180.png",
    });
  });
});
