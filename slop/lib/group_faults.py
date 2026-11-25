from __future__ import annotations

GROUP_HIDDEN_ACK = "group: each add into a hidden group tab is acked truthfully while the DM flood runs"


def register(Fault) -> dict:
    return {
        "group-ack-before-apply": Fault(None, (GROUP_HIDDEN_ACK,), browser=(
            (r"dispatch\(\{(?:\\n|\s)*type: \\?\"add\\?\",(?:\\n|\s)*slot: \{(?:\\n|\s)*accountId: msg\.accountId,"
             r"(?:\\n|\s)*fanId: msg\.fanId(?:\\n|\s)*\},(?:\\n|\s)*reqId: msg\.reqId(?:\\n|\s)*\}\)",
             "(channel.postMessage({ type: 'add-ack', tabId, reqId: msg.reqId, ok: true }), "
             "dispatch({ type: 'add', slot: { accountId: msg.accountId, fanId: msg.fanId } }))"),
        )),
    }
