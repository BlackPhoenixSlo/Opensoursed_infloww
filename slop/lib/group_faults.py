"""/group tab's break-it-once faults (client side, checked by scenarios/2026-10-24-big-model-dm-flood.py):
lib/faults.py merges `register(Fault)` into FAULTS. The check name lives here and the scenario imports it,
so a target can never name a check that does not exist.

Declared bypass: the fault rewrites the app's served JS in the browser actor (actors/ui.py routes), never
service code; the scenario emulates the tab's hidden state (headless Chromium never hides a page).
"""
from __future__ import annotations

GROUP_HIDDEN_ACK = "group: each add into a hidden group tab is acked truthfully while the DM flood runs"


def register(Fault) -> dict:
    return {
        # slop/run 2026-10-24-big-model-dm-flood --break --fault=group-ack-before-apply
        # app/app/group/page.tsx channel.onmessage `add`: the tab acks ok:true on receipt, before slotsReducer
        # applies the add (and the reducer is told no ack is owed), so an add the full tab refuses is acked ok:
        # the sender opens no overflow tab and the fan is lost. Only the hidden-tab add check goes red; the
        # flood's DMs, streams and the group tab's marker renders are untouched.
        "group-ack-before-apply": Fault(None, (GROUP_HIDDEN_ACK,), browser=(
            (r"dispatch\(\{(?:\\n|\s)*type: \\?\"add\\?\",(?:\\n|\s)*slot: \{(?:\\n|\s)*accountId: msg\.accountId,"
             r"(?:\\n|\s)*fanId: msg\.fanId(?:\\n|\s)*\},(?:\\n|\s)*reqId: msg\.reqId(?:\\n|\s)*\}\)",
             "(channel.postMessage({ type: 'add-ack', tabId, reqId: msg.reqId, ok: true }), "
             "dispatch({ type: 'add', slot: { accountId: msg.accountId, fanId: msg.fanId } }))"),
        )),
    }
