# Bundle-derived shapes — NOT captured, NOT verified on the wire

RECIPES.md is captured-only by rule ("Do not add an entry from reading the JS
bundle"). This file is the deliberate other half: shapes read out of
`main.14d24b3e179efdb7.js` and never observed on a live request.

**Everything here is a LEAD, not a recipe.** Bundle reading gets field NAMES and
control flow right and is routinely wrong about what the server actually
requires, what it defaults, and what it rejects. Promote an entry to RECIPES.md
only after seeing it on a real request/response pair.

---

## Mass message = BROADCAST (`send_mass_message`)

Recovered 2026-09-02 from `main.14d24b3e179efdb7.js`.

### The key finding: the send body is an ORDINARY message body

`GroupService.sendMessageToGroup` routes purely on the GROUP's type:

```js
sendMessageToGroup(e){
  ...
  3 === r.type ? this.groupApiService_.sendBroadcastMessage(e, ...)
               : this.groupApiService_.sendMessage(e, ...)
}
```

Both branches pass the SAME object `e` straight through as the POST body:

```js
sendMessage(e,t)         { new z("POST", apiBaseUri_+"/message",           e) }
sendBroadcastMessage(e,t){ new z("POST", apiBaseUri_+"/message/broadcast", e) }
```

So a mass message is NOT a different payload — it is the message body the shim
already builds (`{type, attachments, likes, content, groupId, scheduledFor,
inReplyTo, createdAt}`), POSTed to a different path, where `groupId` is a
**type-3 broadcast group** instead of a DM group. Media/PPV attach exactly as
they do for a DM (the same accountMedia grant recipe), which is why the
two-call attach work already done carries over unchanged.

### Step 1 — mint the broadcast group

`GroupService.createBroadcastGroup(users, recipients, type, groupFlags, groupFlagsMetadata, cb)`
builds a group model and POSTs it to **`POST /api/v1/group`**:

```js
createBroadcastGroup(e,t,r,l,_,p){
  let f = new ul;                       // class ul { users=[]; recipients=[]; lastMessage=null; userSettings=null }
  f.type = r || 2;                      // the modal passes 3
  f.groupFlags = l || 0;                // modal default: this.groupFlags = 32
  f.groupFlagsMetadata = _ || "";
  let h = sessionAccountId;
  if (h) { let w = new Za(h); w.permissionFlags = 65535; f.users.push(w) }   // class Za { userId; permissionFlags }
  for (...e) { if (e[w].userId === h) continue; ...; f.users.push(x) }
  f.recipients = t;
  this.groupApiService_.createGroup(f, ...)   // POST /group
}
```

Derived body:

```json
{"type":3,"groupFlags":32,"groupFlagsMetadata":"",
 "users":[{"userId":"<us>","permissionFlags":65535}],
 "recipients":[{"recipientId":"<listId>","type":30000}],
 "lastMessage":null,"userSettings":null}
```

### Recipients encode the AUDIENCE, and the +1 is EXCLUDE

From the new-message modal:

```js
for (...selectedLists)        r.push({recipientId: list.id, type: 1e3*ServiceIds.ListsService});
for (...selectedExcludeLists) r.push({recipientId: list.id, type: 1e3*ServiceIds.ListsService + 1});
```

`ServiceIds.ListsService = 30`, so:

| type | meaning |
|---|---|
| `30000` | INCLUDE this list |
| `30001` | EXCLUDE this list |

⚠️ **The include/exclude difference is a trailing `+1` on an otherwise identical
row.** Getting it backwards sends the blast to precisely the audience the
operator meant to suppress. This is the single most dangerous field in the flow.

Subscription-tier filtering rides `groupFlagsMetadata` as a doubly-encoded JSON
string (the same nesting style as PPV price metadata):

```js
JSON.stringify({4: JSON.stringify({subscriptionTierId: tier.id})})
```

### Step 2 — send to it

`POST /message/broadcast` with the ordinary message body, `groupId` = the
type-3 group's id.

### Related endpoints (read-side, all bundle-derived)

```
GET  /message/broadcast/stats?before=&limit=          per-broadcast stats
GET  /message/broadcast/stats/deleted?before=&limit=
GET  /message/broadcast/scheduled                     CONFIRMED live (returns [])
POST /message/broadcast/scheduled/{id}/cancel
POST /message/broadcast/scheduled/{id}/edit
```
The history view tracks `stats_total`, `stats_read`, `stats_sales`.

### What is still UNKNOWN — why this stays unshipped

1. **No live exercise.** No broadcast has ever been sent from this account, so
   nothing above has touched a server. The server may require fields the client
   happens to always send, or reject a group with an empty audience.
2. **`groupFlags = 32` is unexplained.** It is the modal's initial value; its
   meaning is not recoverable from the bundle.
3. **This account has 0 subscribers and 0 user lists with members**, so even a
   correct request has no audience — and the only populated threads are REAL
   third-party creators, who must not be blast targets.
4. **Idempotency is unknown.** Whether re-POSTing the same broadcast re-sends to
   everyone is not knowable without trying it. That makes a careless retry
   potentially a duplicate mass-send.
