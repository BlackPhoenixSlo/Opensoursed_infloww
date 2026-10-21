const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { Store } = require("../lib/store");
const { safeStorageCodec, getSecret, setSecret, deleteSecret } = require("../lib/secret");

function tmpStore() {
  return new Store(fs.mkdtempSync(path.join(os.tmpdir(), "secret-test-")));
}

// Reversible stand-in for safeStorage: "enc:" + base64.
function fakeCodec({ available = true, failDecrypt = false } = {}) {
  return {
    available: () => available,
    encrypt: (s) => "enc:" + Buffer.from(s).toString("base64"),
    decrypt: (s) => {
      if (failDecrypt || !s.startsWith("enc:")) throw new Error("bad");
      return Buffer.from(s.slice(4), "base64").toString();
    },
  };
}

test("roundtrip stores only the encrypted field", () => {
  const store = tmpStore();
  const codec = fakeCodec();
  setSecret(store, "shareToken", "tok-123", codec);
  assert.strictEqual(getSecret(store, "shareToken", codec), "tok-123");
  assert.strictEqual(store.get("shareToken"), undefined);
  assert.ok(store.get("shareTokenEnc").startsWith("enc:"));
  const onDisk = fs.readFileSync(store.file, "utf8");
  assert.ok(!onDisk.includes("tok-123"));
});

test("plaintext token from an older build is migrated on read", () => {
  const store = tmpStore();
  store.set("shareToken", "legacy-tok");
  const codec = fakeCodec();
  assert.strictEqual(getSecret(store, "shareToken", codec), "legacy-tok");
  assert.strictEqual(store.get("shareToken"), undefined);
  assert.ok(store.get("shareTokenEnc"));
  assert.strictEqual(getSecret(store, "shareToken", codec), "legacy-tok");
});

test("decrypt failure reads as null (missing), not as a token", () => {
  const store = tmpStore();
  setSecret(store, "shareToken", "tok", fakeCodec());
  assert.strictEqual(getSecret(store, "shareToken", fakeCodec({ failDecrypt: true })), null);
  // Encryption gone since the token was stored: also unreadable.
  assert.strictEqual(getSecret(store, "shareToken", fakeCodec({ available: false })), null);
});

test("dropping an undecryptable token makes it plainly missing (config:save blank path)", () => {
  const store = tmpStore();
  setSecret(store, "shareToken", "tok", fakeCodec());
  const broken = fakeCodec({ failDecrypt: true });
  assert.strictEqual(getSecret(store, "shareToken", broken), null);
  deleteSecret(store, "shareToken");
  assert.strictEqual(getSecret(store, "shareToken", broken), "");
});

test("no encryption available falls back to plaintext, no migration", () => {
  const store = tmpStore();
  const codec = fakeCodec({ available: false });
  setSecret(store, "shareToken", "plain-tok", codec);
  assert.strictEqual(store.get("shareToken"), "plain-tok");
  assert.strictEqual(store.get("shareTokenEnc"), undefined);
  assert.strictEqual(getSecret(store, "shareToken", codec), "plain-tok");
  assert.strictEqual(store.get("shareToken"), "plain-tok");
});

test("missing secret reads as empty; delete clears both fields", () => {
  const store = tmpStore();
  const codec = fakeCodec();
  assert.strictEqual(getSecret(store, "shareToken", codec), "");
  setSecret(store, "shareToken", "tok", codec);
  store.set("shareToken", "stale");
  deleteSecret(store, "shareToken");
  assert.strictEqual(store.get("shareToken"), undefined);
  assert.strictEqual(store.get("shareTokenEnc"), undefined);
});

test("safeStorageCodec refuses Linux basic_text and works with real-ish safeStorage", () => {
  const ss = {
    isEncryptionAvailable: () => true,
    getSelectedStorageBackend: () => "basic_text",
    encryptString: (s) => Buffer.from(s.split("").reverse().join("")),
    decryptString: (b) => b.toString().split("").reverse().join(""),
  };
  assert.strictEqual(safeStorageCodec(ss, "linux").available(), false);
  assert.strictEqual(safeStorageCodec({ ...ss, getSelectedStorageBackend: () => "gnome_libsecret" }, "linux").available(), true);
  const mac = safeStorageCodec(ss, "darwin");
  assert.strictEqual(mac.available(), true);
  assert.strictEqual(mac.decrypt(mac.encrypt("abc")), "abc");
  assert.strictEqual(safeStorageCodec({ isEncryptionAvailable: () => false }, "win32").available(), false);
  assert.strictEqual(safeStorageCodec(undefined).available(), false);
});
