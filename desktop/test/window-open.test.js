const test = require("node:test");
const assert = require("node:assert");

const { isMessagesProRoute, openInMessagesProWindow, sameOriginOpen } = require("../lib/window-open.js");

const APP = "https://app.example.com";
const SIZE = { width: 1470, height: 915 };

test("isMessagesProRoute: Messages Pro and its Deep links, as a path or a URL", () => {
  assert.strictEqual(isMessagesProRoute("/messages-pro"), true);
  assert.strictEqual(isMessagesProRoute("/messages-pro/a/1?fanTab=Ann"), true);
  assert.strictEqual(isMessagesProRoute(`${APP}/messages-pro/a/u/ann`), true);
  assert.strictEqual(isMessagesProRoute("/messages-protest"), false);
  assert.strictEqual(isMessagesProRoute("/group"), false);
  assert.strictEqual(isMessagesProRoute(""), false);
});

test("a Messages Pro link opened as a tab goes into the open Messages Pro window", () => {
  for (const disposition of ["foreground-tab", "background-tab"]) {
    // A named open with no features (the old toast), a target=_blank row, a cmd-click.
    const open = { url: `${APP}/messages-pro/a/1?fanTab=Ann`, frameName: "infloww-rea-x", disposition, features: "" };
    assert.deepStrictEqual(sameOriginOpen(open, true), { messagesPro: true });
    // None open yet: a window of its own, at the Messages Pro size.
    assert.deepStrictEqual(sameOriginOpen(open, false), SIZE);
  }
});

test("an asked-for window stays a window: Messages Pro's own, 'Open in a new window', another page", () => {
  const popout = { url: `${APP}/messages-pro`, frameName: "messages-pro", disposition: "new-window", features: "popup,width=1470,height=915" };
  assert.deepStrictEqual(sameOriginOpen(popout, false), {});
  const another = { url: `${APP}/messages-pro`, frameName: "", disposition: "new-window", features: "popup,width=1470,height=915" };
  assert.deepStrictEqual(sameOriginOpen(another, true), {});
  // "popup" alone was Electron's 800x600.
  const fanWindow = { url: `${APP}/messages-pro/a/1?window=1`, frameName: "", disposition: "new-window", features: "popup" };
  assert.deepStrictEqual(sameOriginOpen(fanWindow, true), SIZE);
  const page = { url: `${APP}/growth/smart-messages?tab=mass`, frameName: "", disposition: "foreground-tab", features: "" };
  assert.deepStrictEqual(sameOriginOpen(page, true), SIZE);
});

// A BrowserWindow as openInMessagesProWindow uses it; `taken`: what its page's
// in-place call answers (a value, or a rejection).
function fakeWindow({ url = `${APP}/messages-pro`, taken = true, destroyed = false } = {}) {
  const calls = { loads: [], scripts: [] };
  return {
    calls,
    isDestroyed: () => destroyed,
    loadURL: (u) => (calls.loads.push(u), Promise.resolve()),
    webContents: {
      getURL: () => url,
      executeJavaScript: (code) => (calls.scripts.push(code), taken instanceof Error ? Promise.reject(taken) : Promise.resolve(taken)),
    },
  };
}
const settle = () => new Promise((r) => setImmediate(r));

test("openInMessagesProWindow: a notification's link goes to the page in place, focused, no reload", async () => {
  const win = fakeWindow();
  const focused = [];
  assert.strictEqual(openInMessagesProWindow(win, "/messages-pro/a/1?fanTab=Ann", APP, (w) => focused.push(w)), true);
  await settle();
  assert.deepStrictEqual(focused, [win]);
  assert.strictEqual(win.calls.scripts.length, 1);
  assert.match(win.calls.scripts[0], /window\.__inflowwOpenNotification\("\/messages-pro\/a\/1\?fanTab=Ann"\) === true/);
  assert.deepStrictEqual(win.calls.loads, []);
});

test("openInMessagesProWindow: a page that does not take it (not up yet, a username link) loads it there", async () => {
  for (const taken of [false, new Error("page gone")]) {
    const win = fakeWindow({ taken });
    assert.strictEqual(openInMessagesProWindow(win, `${APP}/messages-pro/a/u/ann?fanTab=ann`, APP, () => {}), true);
    await settle();
    assert.deepStrictEqual(win.calls.loads, [`${APP}/messages-pro/a/u/ann?fanTab=ann`]);
  }
  // Closed while its page was asked: nothing loads, nothing throws.
  const closing = fakeWindow({ taken: false });
  openInMessagesProWindow(closing, "/messages-pro/a/1?fanTab=Ann", APP, () => {});
  closing.isDestroyed = () => true;
  await settle();
  assert.deepStrictEqual(closing.calls.loads, []);
  // Showing no page of the app's (still blank): loaded, its page never asked.
  const blank = fakeWindow({ url: "about:blank" });
  openInMessagesProWindow(blank, "/messages-pro/a/1?fanTab=Ann", APP, () => {});
  assert.deepStrictEqual(blank.calls.scripts, []);
  assert.deepStrictEqual(blank.calls.loads, [`${APP}/messages-pro/a/1?fanTab=Ann`]);
});

test("openInMessagesProWindow: nothing for no window, another route or another origin", () => {
  const focus = () => assert.fail("focused");
  assert.strictEqual(openInMessagesProWindow(null, "/messages-pro/a/1", APP, focus), false);
  assert.strictEqual(openInMessagesProWindow(fakeWindow({ destroyed: true }), "/messages-pro/a/1", APP, focus), false);
  assert.strictEqual(openInMessagesProWindow(fakeWindow(), "/messages-pro/a/1", "", focus), false);
  for (const route of ["/group", "//evil.example/messages-pro/a/1", "https://evil.example/messages-pro/a/1"]) {
    const win = fakeWindow();
    assert.strictEqual(openInMessagesProWindow(win, route, APP, focus), false, route);
    assert.deepStrictEqual(win.calls, { loads: [], scripts: [] });
  }
});
