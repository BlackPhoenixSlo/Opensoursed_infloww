"use strict";

// OS-encrypted secrets in the config store (today: only the relay share token).
//
// The value is encrypted with Electron's `safeStorage` (macOS Keychain, Windows
// DPAPI, Linux libsecret/kwallet) and kept base64 under `<key>Enc`. When the OS
// offers no real encryption — `isEncryptionAvailable()` false, or Linux falling
// back to the 'basic_text' backend, which is a hardcoded key — we keep the old
// plaintext `<key>` field (the file is still mode 600). A plaintext value left
// by an older build is moved to `<key>Enc` on first read.
//
// The codec is injected so this module never requires electron (unit tests use
// a fake). Codec shape: { available(), encrypt(str) -> base64, decrypt(base64) -> str }.

function safeStorageCodec(safeStorage, platform = process.platform) {
  return {
    available() {
      try {
        if (!safeStorage || !safeStorage.isEncryptionAvailable()) return false;
        if (platform === "linux" && typeof safeStorage.getSelectedStorageBackend === "function") {
          return safeStorage.getSelectedStorageBackend() !== "basic_text";
        }
        return true;
      } catch {
        return false;
      }
    },
    encrypt: (plain) => safeStorage.encryptString(plain).toString("base64"),
    decrypt: (b64) => safeStorage.decryptString(Buffer.from(b64, "base64")),
  };
}

const encKey = (key) => `${key}Enc`;

function setSecret(store, key, value, codec) {
  if (codec.available()) {
    store.set(encKey(key), codec.encrypt(value));
    if (store.get(key) !== undefined) store.delete(key);
  } else {
    store.set(key, value);
    if (store.get(encKey(key)) !== undefined) store.delete(encKey(key));
  }
}

function deleteSecret(store, key) {
  if (store.get(key) !== undefined) store.delete(key);
  if (store.get(encKey(key)) !== undefined) store.delete(encKey(key));
}

// Returns the secret, "" when none is stored, or null when one is stored but
// can't be decrypted (keychain denied, encryption gone, corrupt value). Callers
// treat null as "missing, ask again".
function getSecret(store, key, codec) {
  const enc = store.get(encKey(key));
  if (typeof enc === "string" && enc) {
    if (!codec.available()) return null;
    try {
      return String(codec.decrypt(enc));
    } catch {
      return null;
    }
  }
  const plain = String(store.get(key, "") || "");
  if (plain && codec.available()) {
    try {
      setSecret(store, key, plain, codec); // migrate: encrypt, drop the plaintext
    } catch {
      /* encryption failed — keep using the plaintext copy */
    }
  }
  return plain;
}

module.exports = { safeStorageCodec, getSecret, setSecret, deleteSecret };
