/**
 * proxy.ts's matcher is spelled out for Next's static analysis; it must still name every BOOTED route and the
 * header the proxy drops.
 */
import { describe, expect, it } from "vitest";

import { BOOT_PATH_HEADER, BOOTED } from "@/lib/inlineBoot";

import { config } from "./proxy";

describe("proxy config.matcher", () => {
  it("covers every BOOTED route and BOOT_PATH_HEADER", () => {
    const paths = config.matcher.filter((m): m is string => typeof m === "string");
    expect(new Set(paths)).toEqual(new Set(BOOTED));
    const tagged = config.matcher.filter((m) => typeof m !== "string");
    expect(tagged).toEqual([{ source: "/:path*", has: [{ type: "header", key: BOOT_PATH_HEADER }] }]);
  });
});
