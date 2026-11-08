/**
 * Tags a document GET of a route whose HTML carries an inline boot (lib/inlineBoot.server.ts) with its path and
 * query: the root layout, which starts those relay reads, is not told the URL. Anything else (an RSC fetch of a
 * client navigation or a prefetch, a refresh, any other route) goes untagged, and a tag the client sent is dropped on
 * every route (the matcher's second entry): the layout starts relay reads only for those document loads.
 */
import { NextResponse, type NextRequest } from "next/server";

import { BOOT_PATH_HEADER, BOOTED } from "@/lib/inlineBoot";

export function proxy(req: NextRequest) {
  const headers = new Headers(req.headers);
  headers.delete(BOOT_PATH_HEADER);
  const dest = headers.get("sec-fetch-dest");
  if (BOOTED.has(req.nextUrl.pathname) && req.method === "GET" && !headers.has("rsc")
    && !headers.has("next-router-prefetch") && (!dest || dest === "document")) {
    headers.set(BOOT_PATH_HEADER, req.nextUrl.pathname + req.nextUrl.search);
  }
  return NextResponse.next({ request: { headers } });
}

// Static for Next's analysis: BOOTED's routes and BOOT_PATH_HEADER's value spelled out.
export const config = {
  matcher: ["/", "/messages-pro", { source: "/:path*", has: [{ type: "header", key: "x-chatterly-boot-path" }] }],
};
