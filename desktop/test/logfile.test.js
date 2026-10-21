const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { redact, createLogFile, mirrorConsole } = require("../lib/logfile");

const tmpDir = () => path.join(fs.mkdtempSync(path.join(os.tmpdir(), "logfile-test-")), "logs");

test("redact hides t= query values and known secrets", () => {
  assert.strictEqual(
    redact("load https://x.test/inbox?t=abc123&x=1 and /a?b=2&t=zz#h"),
    "load https://x.test/inbox?t=[redacted]&x=1 and /a?b=2&t=[redacted]#h",
  );
  assert.strictEqual(redact("cookie share_token=s3cr3t-tok", ["s3cr3t-tok"]), "cookie share_token=[redacted]");
  assert.strictEqual(redact("start=5 at=1"), "start=5 at=1");
  assert.strictEqual(redact("abc", [""]), "abc");
});

test("rotates to two files of at most maxBytes", () => {
  const dir = tmpDir();
  const log = createLogFile({ dir, maxBytes: 100, files: 2 });
  for (let i = 0; i < 20; i++) log.write(`line ${String(i).padStart(2, "0")} ${"x".repeat(20)}`);
  const files = fs.readdirSync(dir).sort();
  assert.deepStrictEqual(files, ["main.1.log", "main.log"]);
  for (const f of files) assert.ok(fs.statSync(path.join(dir, f)).size <= 100);
  assert.match(fs.readFileSync(path.join(dir, "main.log"), "utf8"), /line 19/);
  assert.doesNotMatch(fs.readFileSync(path.join(dir, "main.1.log"), "utf8"), /line 00/);
});

test("write redacts the live secret and survives a throwing getSecrets", () => {
  const dir = tmpDir();
  let token = "tok-live-1";
  const log = createLogFile({ dir, getSecrets: () => [token] });
  log.write("seed tok-live-1");
  token = null;
  const broken = createLogFile({ dir, getSecrets: () => { throw new Error("not ready"); } });
  broken.write("before ready ?t=raw");
  const text = fs.readFileSync(log.file, "utf8");
  assert.ok(!text.includes("tok-live-1"));
  assert.ok(!text.includes("raw"));
  assert.strictEqual(text.split("\n").filter(Boolean).length, 2);
});

test("mirrorConsole still prints and also writes each level", () => {
  const printed = [];
  const fakeConsole = { log: (...a) => printed.push(a.join(" ")), error: (...a) => printed.push(a.join(" ")) };
  const lines = [];
  mirrorConsole(fakeConsole, { write: (l) => lines.push(l) }, () => "T");
  fakeConsole.log("hello %s", "world");
  fakeConsole.error("boom", 42);
  assert.deepStrictEqual(printed, ["hello %s world", "boom 42"]);
  assert.deepStrictEqual(lines, ["T [log] hello world", "T [error] boom 42"]);
});
