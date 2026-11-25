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

// No OF read reports its current folder sort: the label is the last sort OF took, kept per Creator in this browser.
export function parseFolderSort(raw: string | null): FolderSortState {
  let v: { sort?: unknown; order?: unknown } | null = null;
  try {
    v = raw ? JSON.parse(raw) : null;
  } catch { }
  return v && isFolderSort(v.sort) && isFolderOrder(v.order) ? { sort: v.sort, order: v.order } : DEFAULT_FOLDER_SORT;
}

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
  } catch { }
}
