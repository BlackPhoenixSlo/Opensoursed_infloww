import { describe, it, expect } from "vitest";

import { bucketOf } from "./CompetitorReports";

describe("bucketOf", () => {
  it("routes paid feed-post revenue to posts", () => {
    expect(bucketOf("ppv_post")).toBe("posts");
    expect(bucketOf("tip_post")).toBe("posts");
  });

  it("routes stream revenue to other, never messages", () => {
    expect(bucketOf("ppv_stream")).toBe("other");
    expect(bucketOf("tip_stream")).toBe("other");
  });

  it("keeps chat PPV in messages", () => {
    expect(bucketOf("ppv")).toBe("messages");
    expect(bucketOf("ppv_message")).toBe("messages");
  });

  it("counts paid customs in messages, as the Dashboard's Messages tile does (#44)", () => {
    expect(bucketOf("custom")).toBe("messages");
  });

  it("maps subscriptions, rebills and plain tips", () => {
    expect(bucketOf("subscription")).toBe("subscriptions");
    expect(bucketOf("rebill")).toBe("subscriptions");
    expect(bucketOf("tip")).toBe("tips");
  });

  it("falls back to other for null / unknown kinds", () => {
    expect(bucketOf(null)).toBe("other");
    expect(bucketOf("chargeback")).toBe("other");
  });
});
