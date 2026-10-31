/** extractError: OF's `error.message` out of a wrapped relay error, else an HTTP line, else the Error's message. */
import { describe, expect, it } from "vitest";

import { extractError } from "@/components/settings/extractError";
import { RelayError } from "@/lib/relay";

const upstream = (raw: unknown) => ({ detail: { upstream_body: raw } });

describe("extractError", () => {
  it.each<[string, unknown, string]>([
    ["relay: OF error.message in upstream_body",
      new RelayError(400, upstream(JSON.stringify({ error: { message: "Price too low" } })), "bad"), "Price too low"],
    ["relay: upstream_body not JSON", new RelayError(502, upstream("<html>"), "bad gateway"), "HTTP 502 — bad gateway"],
    ["relay: upstream JSON without error.message",
      new RelayError(400, upstream(JSON.stringify({ error: { code: 1 } })), "bad"), "HTTP 400 — bad"],
    ["relay: upstream error.message empty",
      new RelayError(400, upstream(JSON.stringify({ error: { message: "" } })), "bad"), "HTTP 400 — bad"],
    ["relay: upstream_body not a string", new RelayError(400, upstream({ error: { message: "x" } }), "bad"), "HTTP 400 — bad"],
    ["relay: string detail (FastAPI)", new RelayError(404, { detail: "Not Found" }, "nf"), "HTTP 404 — nf"],
    ["relay: pydantic detail list", new RelayError(422, { detail: [{ loc: ["body", "text"], msg: "required" }] }, "unprocessable"),
      "HTTP 422 — unprocessable"],
    ["relay: no body, default message", new RelayError(500, undefined), "HTTP 500 — relay 500"],
    ["relay: null body", new RelayError(503, null, "down"), "HTTP 503 — down"],
    ["plain Error", new Error("network down"), "network down"],
    ["Error with empty message", new Error(""), "unknown error"],
    ["object with message", { message: "custom" }, "custom"],
    ["string", "boom", "unknown error"],
    ["null", null, "unknown error"],
    ["undefined", undefined, "unknown error"],
  ])("%s", (_name, err, want) => {
    expect(extractError(err)).toBe(want);
  });
});
