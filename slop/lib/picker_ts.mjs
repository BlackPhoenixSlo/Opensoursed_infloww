// The chat vault picker's folder menu on the relay's answers, through lib/app_ts.py (the
// app's own TypeScript in node): what VaultPicker's folder dropdown lists for a chatter.
//
// Input: {access, lists}: `access` is GET /chatter/me/folder-access?account_id= as the
// chatter got it (useChatterFolderAccess), `lists` every row of GET /api/of/v2/vault/lists
// pages as the chatter got them (fetchAllVaultLists, merged). Output: {restricted, items}:
// components/chat/vaultPickerFolders `folderSelectItems` on the picker's inputs, `lists`
// first through useVaultLists' select (copied, the one copy here: private to the hook):
// custom folders with media only.
export async function run(load, input) {
  const folders = await load("/components/chat/vaultPickerFolders.ts");
  const restricted = !!input.access?.restricted;
  const lists = (input.lists ?? []).filter((l) => l.type === "custom" && l.hasMedia);
  return { restricted, items: folders.folderSelectItems(restricted, input.access?.folders ?? [], lists) };
}
