import { NextResponse, type NextRequest } from "next/server";

import { BOOT_PATH_HEADER, BOOTED } from "@/lib/inlineBoot";

export function proxy(req: NextRequest) {
  const headers = new Headers(req.headers);
  // a client-sent tag is never trusted: drop it on every route
  headers.delete(BOOT_PATH_HEADER);
  const dest = headers.get("sec-fetch-dest");
  if (BOOTED.has(req.nextUrl.pathname) && req.method === "GET" && !headers.has("rsc")
    && !headers.has("next-router-prefetch") && (!dest || dest === "document")) {
    headers.set(BOOT_PATH_HEADER, req.nextUrl.pathname + req.nextUrl.search);
  }
  return NextResponse.next({ request: { headers } });
}

// Static for Next's analysis: spelled out, not BOOTED/BOOT_PATH_HEADER
export const config = {
  matcher: ["/", "/messages-pro", { source: "/:path*", has: [{ type: "header", key: "x-chatterly-boot-path" }] }],
};
