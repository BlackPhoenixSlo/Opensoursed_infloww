"use strict";

// Fake proof for the Go live window (ticket 127): real Electron, fully offline.
// Every https/http request of the window's partition is answered by a local
// stub page (protocol.handle), and DNS is mapped to nothing, so onlyfans.com is
// never contacted. The stub shows what the page can see: localStorage
// bcTokenSha, document.cookie (non-HttpOnly), the UA, and whether a logout
// request got through; the partition's jar is read for the HttpOnly sess
// (protocol.handle requests carry no Cookie header, measured).
// Fake values only.
//
// Run (from desktop/):  nice -n 10 npx electron test/go-live-fake-proof.js [outDir]
// Prints one JSON line and exits 0 when every check holds, 1 otherwise.

const fs = require("node:fs");
const path = require("node:path");
const { app, BrowserWindow, session } = require("electron");
const { openOfLiveWindow } = require("../lib/of-live-window");
const { chromeMajor } = require("../lib/of-ua");

app.commandLine.appendSwitch("host-resolver-rules", "MAP * ~NOTFOUND");

const OUT = process.argv.find((a, i) => i > 1 && !a.startsWith("-") && !a.endsWith(".js")) || "/tmp/ofm-127-fake-proof";
const XBC = "fake-xbc-1234";
const COOKIES = [
  { name: "auth_id", value: "1000001", domain: ".onlyfans.com", path: "/", secure: true, httpOnly: false, expires: null },
  { name: "sess", value: "fake-sess-5678", domain: ".onlyfans.com", path: "/", secure: true, httpOnly: true, expires: null },
  { name: "__cf_bm", value: "fake-cf", domain: ".onlyfans.com", path: "/", secure: true, httpOnly: true, expires: null },
];
const STUB = `<!doctype html><title>stub</title><pre id="o" style="font:16px monospace;white-space:pre-wrap"></pre>
<script>
(async () => {
  let logout = "reached";
  try { await fetch("/api2/v2/users/logout", { method: "POST" }); } catch (e) { logout = "blocked"; }
  const seen = { bcTokenSha: localStorage.getItem("bcTokenSha"), documentCookie: document.cookie,
                 userAgent: navigator.userAgent, logout };
  document.getElementById("o").textContent = "STUB onlyfans.com" + location.pathname + "\\n" + JSON.stringify(seen, null, 2);
  window.__seen = seen;
})();
</script>`;

const requests = [];
const handled = new Set();
const fakeSession = {
  fromPartition(p) {
    const s = session.fromPartition(p);
    if (!handled.has(p)) {
      handled.add(p);
      const answer = (req) => {
        requests.push({ url: req.url, method: req.method, cookie: req.headers.get("cookie") || "" });
        return new Response(STUB, { headers: { "content-type": "text/html" } });
      };
      s.protocol.handle("https", answer);
      s.protocol.handle("http", answer);
    }
    return s;
  },
};

app.whenReady().then(async () => {
  let ok = false;
  const result = {};
  try {
    const win = await openOfLiveWindow(
      { BrowserWindow, session: fakeSession },
      { creatorId: "1000001", cookies: COOKIES, xBc: XBC, platform: process.platform, chromeMajor: chromeMajor(process.versions) },
    );
    const wc = win.webContents;
    let seen = null;
    for (let i = 0; i < 50 && !seen; i++) {
      await new Promise((r) => setTimeout(r, 100));
      seen = await wc.executeJavaScript("window.__seen || null").catch(() => null);
    }
    const page = requests.find((r) => r.url === "https://onlyfans.com/my/streaming");
    const jar = await session.fromPartition("of-live-1000001").cookies.get({ url: "https://onlyfans.com/" });
    const sess = jar.find((c) => c.name === "sess");
    Object.assign(result, {
      partition: "of-live-1000001",
      seen,
      streamingPageServed: !!page,
      jar: jar.map((c) => ({ name: c.name, httpOnly: c.httpOnly, domain: c.domain })),
      logoutRequestsReachingStub: requests.filter((r) => /logout/.test(r.url)).length,
    });
    const checks = {
      bcTokenSha: !!seen && seen.bcTokenSha === XBC,
      streamingPageServed: !!page,
      sessHttpOnly: !!sess && sess.value === "fake-sess-5678" && sess.httpOnly && !/sess=/.test(seen.documentCookie),
      authIdVisible: !!seen && /auth_id=\d{7}/.test(seen.documentCookie),
      noCloudflare: !jar.some((c) => c.name === "__cf_bm"),
      uaNoElectron: !!seen && !/Electron/i.test(seen.userAgent),
      logoutBlocked: !!seen && seen.logout === "blocked" && result.logoutRequestsReachingStub === 0,
    };
    result.checks = checks;
    ok = Object.values(checks).every(Boolean);
    fs.mkdirSync(OUT, { recursive: true });
    const img = await wc.capturePage();
    result.screenshot = path.join(OUT, "go-live-stub.png");
    fs.writeFileSync(result.screenshot, img.toPNG());
    win.close();
  } catch (err) {
    result.error = err && err.message;
  }
  console.log(JSON.stringify({ ok, ...result }));
  app.exit(ok ? 0 : 1);
});
