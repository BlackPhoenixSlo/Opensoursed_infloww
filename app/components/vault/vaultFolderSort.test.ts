import { describe, expect, it } from "vitest";

import { DEFAULT_FOLDER_SORT, folderSortAfter, parseFolderSort } from "./vaultFolderSort";

describe("parseFolderSort", () => {
  it.each([
    ["nothing stored", null, DEFAULT_FOLDER_SORT],
    ["a stored sort", JSON.stringify({ sort: "custom", order: "desc" }), { sort: "custom", order: "desc" }],
    ["an unknown sort", JSON.stringify({ sort: "size", order: "asc" }), DEFAULT_FOLDER_SORT],
    ["an unknown order", JSON.stringify({ sort: "name", order: "up" }), DEFAULT_FOLDER_SORT],
    ["not JSON", "{", DEFAULT_FOLDER_SORT],
    ["JSON null", "null", DEFAULT_FOLDER_SORT],
  ] as const)("%s", (_, raw, want) => {
    expect(parseFolderSort(raw)).toEqual(want);
  });
});

describe("folderSortAfter", () => {
  // The relay's rule (service/vault_ai_api.py sort_of_folders): sort or "recent", order or "desc".
  const prev = { sort: "name", order: "asc" } as const;
  it.each([
    ["a sort and order", { sort: "recent", order: "desc" }, { sort: "recent", order: "desc" }],
    ["a custom order keeps the order", { customOrder: [3, 1] }, { sort: "custom", order: "asc" }],
    ["a custom order wins over a sort", { sort: "media", order: "desc", customOrder: [1] }, { sort: "custom", order: "asc" }],
    ["an empty custom order is the sort sent", { sort: "media", order: "desc", customOrder: [] }, { sort: "media", order: "desc" }],
    ["no order is the relay's desc", { sort: "media" }, { sort: "media", order: "desc" }],
    ["nothing sent is the relay's recent desc", {}, { sort: "recent", order: "desc" }],
    ["a sort the label cannot name is the default", { sort: "size", order: "desc" }, DEFAULT_FOLDER_SORT],
  ] as const)("%s", (_, sent, want) => {
    expect(folderSortAfter(prev, sent)).toEqual(want);
  });
});
