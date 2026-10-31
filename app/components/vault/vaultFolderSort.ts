/**
 * The Vault rail's folder sort (Layout capture growth-vault-pro#20, #22): the OF folder-list sort the relay's
 * `/admin/vault-ai/of-folders/sort` sets. No read reports OF's current folder sort, so the label is the last sort
 * OF took from any page (`sortOfFolders` saves it), kept per Creator in this browser (`loadFolderSort` /
 * `saveFolderSort`); "Default" ascending until one is picked.
 */

export const FOLDER_SORTS = [
  { value: "default", label: "Default" },
  { value: "name", label: "Name" },
  { value: "recent", label: "Recent" },
  { value: "media", label: "Media" },
  { value: "custom", label: "Custom" },
] as const;
export const FOLDER_ORDERS = [
  { value: "asc", label: "Ascending" },
  { value: "desc", label: "Descending" },
] as const;
export type FolderSort = (typeof FOLDER_SORTS)[number]["value"];
export type FolderOrder = (typeof FOLDER_ORDERS)[number]["value"];
export interface FolderSortState { sort: FolderSort; order: FolderOrder }
export const DEFAULT_FOLDER_SORT: FolderSortState = { sort: "default", order: "asc" };

function isFolderSort(v: unknown): v is FolderSort {
  return FOLDER_SORTS.some((o) => o.value === v);
}
function isFolderOrder(v: unknown): v is FolderOrder {
  return FOLDER_ORDERS.some((o) => o.value === v);
}

/** A stored folder sort, or the default for nothing stored or anything unreadable. */
export function parseFolderSort(raw: string | null): FolderSortState {
  let v: { sort?: unknown; order?: unknown } | null = null;
  try {
    v = raw ? JSON.parse(raw) : null;
  } catch { /* unreadable: the default */ }
  return v && isFolderSort(v.sort) && isFolderOrder(v.order) ? { sort: v.sort, order: v.order } : DEFAULT_FOLDER_SORT;
}

/** The label once OF took a sort (`sortOfFolders`, from any page), by the relay's rule (service/vault_ai_api.py
 *  `sort_of_folders`): a custom order (non-empty) is "custom", the order kept; else the sort and order sent, "recent"
 *  and "desc" for none sent; one the label cannot name is the default, as `parseFolderSort`'s. */
export function folderSortAfter(
  prev: FolderSortState,
  sent: { sort?: string; order?: string; customOrder?: readonly unknown[] },
): FolderSortState {
  if (sent.customOrder?.length) return { sort: "custom", order: prev.order };
  const sort = sent.sort || "recent";
  const order = sent.order || "desc";
  return isFolderSort(sort) && isFolderOrder(order) ? { sort, order } : DEFAULT_FOLDER_SORT;
}

function folderSortKey(accountId: string): string {
  return `chatterly:vault-folder-sort:v1:${accountId}`;
}

/** A Creator's last folder sort set here; the default with storage off. */
export function loadFolderSort(accountId: string): FolderSortState {
  try {
    return parseFolderSort(window.localStorage.getItem(folderSortKey(accountId)));
  } catch {
    return DEFAULT_FOLDER_SORT;
  }
}

export function saveFolderSort(accountId: string, s: FolderSortState): void {
  try {
    window.localStorage.setItem(folderSortKey(accountId), JSON.stringify(s));
  } catch { /* storage full or off: the label lasts until the reload */ }
}
