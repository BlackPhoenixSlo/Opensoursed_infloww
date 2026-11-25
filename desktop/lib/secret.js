"use strict";


function safeStorageCodec(safeStorage, platform = process.platform) {
  return {
    available() {
      try {
        if (!safeStorage || !safeStorage.isEncryptionAvailable()) return false;
        if (platform === "linux" && typeof safeStorage.getSelectedStorageBackend === "function") {
          // Linux basic_text backend is a hardcoded key: not encryption
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

// "" when none stored, null when stored but undecryptable (keychain denied, corrupt): callers treat null as missing
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
      setSecret(store, key, plain, codec);
    } catch {
    }
  }
  return plain;
}

module.exports = { safeStorageCodec, getSecret, setSecret, deleteSecret };
