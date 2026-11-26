# Split Inbox groups are bound per chatter and filtered on the relay

**Status: accepted** (owner and client AE, 2026-11-23). Supersedes ADR-0004's "not bound to Employees"; its store (the Creator's `account_ai_config.split_inbox_json`, one split for every Employee and device) stands.

A big Creator has 2–3 chatters, and each must see only their own Fans. The owner binds each chatter to one group in the Split Inbox dialog. The binding is stored as `chatter_groups: {chatter_id: group}` inside the same `split_inbox_json`, so no migration is needed. A Fan's group is its explicit move if it has one; otherwise it is `fan_id mod N + 1`. A non-numeric id goes to group 1. The app (`groupOf`, computed over the digit string so there is no precision loss) and the relay (`split_inbox.group_of`) use the same rule.

The relay enforces the binding with `split_inbox.chatter_inbox_filter`. It is a no-op for an owner (any User cookie, dual-cookie sessions included, DA-1), for an unbound chatter, and for a Creator with one group. For a bound chatter, it narrows:

- the chat list (search included)
- the local chat list seed
- the focus queue
- SSE frames, live and replayed
- web push

Two kinds of count change for a bound chatter:

- **Roster badges** are rebuilt from the held 25-chat window, narrowed to the group. They are approximate, the same as the Amber circle.
- **Whole-inbox counts** (the Red circle total, `creator_warmed.roster`, the freshness `unread_total`) are withheld.

`hasMore` stays as OnlyFans sent it, so the Fan List keeps paging past a short filtered page. A bound chatter's selector is locked to their group and offers no "All inboxes"; the owner keeps the full selector.

Saving goes through `PATCH /admin/split-inbox`, which sends only the owner's edits (`group_count`, `chatter_groups`, and `assignments` for one Creator). The relay applies them to every named Creator's stored config in one transaction, so a stale view cannot revert another device's changes. An edit to a group above the resulting count is refused 409 (nothing written), and a chatter binding lands only on the Creators that chatter is granted. The All Models dialog applies the count and chatter bindings to every Creator in view; moving single Fans is only possible for one Creator. `PUT` stays for old open tabs.

**Agency default.** An All Models save sends `as_default: true`. In the same transaction, the relay stores the owner's default in `user_settings` (tab `split_inbox_default`, so no migration is needed). The default is taken from the saved result, not from the edits. Its count is the one every target now shares; if the targets differ, the previous default's count is kept. A chatter's binding enters the default when it is the same on every target that chatter is granted; differing or missing bindings are left out. So owners who split before this get a correct default on their first All Models save. The default holds no Fan moves. A Creator with no `split_inbox_json` resolves to its owner's default everywhere the relay reads a config (GET, `warm`, `config`). The default's bindings are inherited unfiltered: a binding for a chatter not granted that Creator does nothing, and it takes effect as soon as a grant lands, so a grant change needs no cache refresh. A Creator linked to several owners inherits only when exactly one of them has a default or all their defaults are equal; otherwise it has no split, so one agency's default never leaks onto another's. Once the Creator has its own save, that save wins. After the commit, the relay re-resolves the saving owner's inherited configs it has cached; if that refresh fails, it is logged and the save still succeeds.

## Considered Options

- **Keep groups unbound (ADR-0004).** Rejected because the client needs each chatter to see only their own group, and an unbound selector enforces nothing.
- **A hash spread or a stored per-Fan table.** Rejected because mod N is the smallest rule both sides compute identically, and explicit moves already cover the exceptions (owner: YAGNI).
- **A separate table for bindings.** Rejected because it would need a migration, while the per-Creator JSON already holds the split.

## Consequences

- **Opening a chat directly by Fan id is not filtered** (`/chats/{id}`, its messages). This keeps shared links and notification deep-links working. The binding narrows what a chatter is shown; it is not an access control on single chats.
- **Lowering N drops bindings above it.** Those chatters become unbound, which means they see every group.
- **The config is cached in RAM per relay process.** The GET and PUT routes refresh it. A second relay process would serve a stale binding until its next GET.
- **The OF notification feed and frames that carry no Fan id are not filtered.**
