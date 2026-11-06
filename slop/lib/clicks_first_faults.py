"""The clicks-first flow's break-it-once faults (scenarios/2026-11-05-clicks-first.py): lib/faults.py merges
`register(Fault)` into FAULTS. The check names live here and the scenario imports them.
"""
from __future__ import annotations

PER_CREATOR = 2  # app/lib/relaySchedule.ts PER_CREATOR: the relay's background lane per Creator
C_CAP = (f"no Creator (but the tapped one) has more than {PER_CREATOR} background OnlyFans reads on the wire at once "
         "(the queue holds the rest)")
C_ABORT = "leaving the Dashboard mid-load sends none of its queued fan-count / new-fan reads after the switch"
C_SNAPSHOT = ("a reload paints every Per-model card's fan count from the saved snapshot before any fan-count read "
              "answers, the figure the settled page shows")

# app/components/providers.tsx before 2026-11-05: the per-Creator badge and roster keys (of-profile, of-sub-counts,
# of-new-fans, of-notif-count) left out of the saved snapshot, so a reload reads every Creator again before a card
# shows a number.
_KEYS_UNPERSISTED = """(() => {
  const put = IDBObjectStore.prototype.put;
  const dropped = (k) => Array.isArray(k) && ['of-profile', 'of-sub-counts', 'of-new-fans', 'of-notif-count'].includes(k[0]);
  IDBObjectStore.prototype.put = function (value, key) {
    if (this.name === 'snapshot' && typeof value === 'string') {
      try {
        const c = JSON.parse(value), qs = c && c.clientState && c.clientState.queries;
        if (Array.isArray(qs)) { c.clientState.queries = qs.filter((q) => !dropped(q.queryKey)); value = JSON.stringify(c); }
      } catch (e) { /* not the snapshot's JSON: written as is */ }
    }
    return put.call(this, value, key);
  };
})();"""


def register(Fault) -> dict:
    return {
        # slop/run clicks-first --break: a Creator's lane never fills (app/lib/relaySchedule.ts `admissible` reads
        # `<state>.perCreator` as 1e9), so every background read goes out at once as before. The production build
        # keeps the property name; one shared chunk holds the module.
        # Nothing waits, so leaving has nothing to drop: C_ABORT too.
        "relay-scheduler-bypassed": Fault(None, (C_CAP, C_ABORT), browser=((r"\w+\.perCreator\b", "1e9"),)),
        # slop/run clicks-first --break --fault=badge-keys-unpersisted
        "badge-keys-unpersisted": Fault(None, (C_SNAPSHOT,), browser_js=_KEYS_UNPERSISTED),
    }
