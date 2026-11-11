"""The clicks-first flow's break-it-once faults (scenarios/2026-11-05-clicks-first.py): lib/faults.py merges
`register(Fault)` into FAULTS. The check names live here and the scenario imports them.
"""
from __future__ import annotations

C_CAP = "no Creator (but the tapped one) exceeds the background OnlyFans read cap on the wire"
C_ABORT = "leaving Creator reports extras mid-load sends none of its queued fan-count / new-fan reads after the switch"
C_SNAPSHOT = ("a reload paints every Per-model card's fan count from the saved snapshot before any fan-count read "
              "answers, the figure the settled page shows")
C_BUNDLE = ("one call per screen: dash-first, reports-first extras and mp-first send 0 per-Creator OnlyFans reads of the bundle's "
            "routes (by path; the money rail's feeds keep theirs), one screen bundle each (+ at most one follow-up for late Creators)")
C_PARTIAL = ("a slow Creator (OF +3 s, bundle deadline 2 s): every card keeps its saved fan count (never blank), the "
             "page sends 1 bundle + at most 1 follow-up and 0 per-Creator OnlyFans reads; the late read landed in the "
             "relay's cache (the next bundle has that Creator complete, no OnlyFans call)")
C_ENTRY = ("document entry: Messages Pro's bundle (and Dashboard's first-visit guess) comes with the HTML or "
           "leaves before /auth/me answers; Dashboard first/reload Applied settings keep their entry timing; "
           "Dashboard reload sends no card bundle (grid=false)")

# app/components/auth/AuthGate.tsx before 2026-11-06: the screen bundle and the Applied settings read wait for the auth
# probe (the bundle for its screen's first card, the settings for the principal in their query key). Emulated at the
# page's fetch: both are held until /auth/me has answered (the page's own: with it, the HTML's inline boot is off).
AFTER_PROBE_JS = """(() => {
  const f = window.fetch;
  let probed;
  const answered = new Promise((r) => { probed = r; });
  window.fetch = function (input, init) {
    const u = typeof input === 'string' ? input : (input && input.url) || String(input);
    if (u.includes('/auth/me')) {
      const p = f.apply(this, arguments);
      p.finally(probed);
      return p;
    }
    if (u.includes('/admin/screens/') || u.includes('/admin/settings/applied')) {
      const self = this, args = arguments;
      return answered.then(() => f.apply(self, args));
    }
    return f.apply(this, arguments);
  };
})();"""



def _bundles_unused() -> None:
    """app/lib/screenBundle.ts unused (the app before 2026-11-05, or the relay without /admin/screens/*): every bundle
    answers 404, to the browser and to the HTML's inline boot alike, so each read goes out per Creator as before."""
    import server
    from starlette.responses import JSONResponse

    async def gone(request, call_next):
        if request.url.path.startswith("/admin/screens/"):
            return JSONResponse({"detail": "slop: no screen bundles"}, status_code=404)
        return await call_next(request)

    server._http_hooks.add(gone)


def _html_reads_refused() -> None:
    """The app before the HTML's inline boot (2026-11-06): the page fetches /auth/me, the bundle and the settings
    itself (lib/screens_faults.py's `inline-boot-relay-refuses-server`: the Next server's reads get a 503)."""
    import importlib
    importlib.import_module(f"{__package__}.screens_faults" if __package__ else "screens_faults") \
        ._inline_boot_relay_refuses_server()

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
        # slop/run clicks-first --break --fault=screen-bundle-unused: the per-Creator fan-out (main before PR B)
        "screen-bundle-unused": Fault(_bundles_unused, (C_BUNDLE, C_PARTIAL)),
        # slop/run clicks-first --break --fault=screen-bundle-after-probe: the bundle and settings behind /auth/me
        "screen-bundle-after-probe": Fault(_html_reads_refused, (C_ENTRY,), browser_js=AFTER_PROBE_JS),
    }
