from __future__ import annotations

PUSH_ALL_ONCE = ("push: every enabled, in-scope arrival (steady, re-offer, replay, restart, prune phases) "
                 "reaches every live subscription that should get it exactly once (2xx at the push service, by tag)")
PUSH_SCOPE = ("push: no subscription gets a Creator its session does not see (a chatter outside its Creators, "
              "an Agency another Agency's)")
PUSH_TYPES = ("push: a muted type, a platform switched off, or an OF type the app cannot name -> 0 pushes")
PUSH_ORDER = "push: steady phase, per subscription and Creator, pushes arrive in frame order"
PUSH_NO_REPUSH = ("push: a purchase re-offered 3x, an SSE replay (Last-Event-ID) and a relay restart's re-offer "
                  "add 0 pushes (at most 1 per subscription and tag)")
PUSH_PRUNED_GONE = ("push: a subscription the push service answers 410 is pruned (row gone) and gets no later "
                    "request")
PUSH_PRUNED_DEAD = ("push: a logged-out session (POST /auth/logout, or Log out other sessions) loses its "
                    "subscription row and gets no later request")
PUSH_DECRYPT = ("push: every request body decrypts (aes128gcm, the device's keys) to the notice JSON "
                "{v, tag, title, body, href, type, account_id}")
PUSH_VAPID = ("push: every request carries a valid VAPID JWT (ES256 under the relay's /push/key, aud = endpoint "
              "origin, sub mailto: public host, exp <= 24 h)")
UI_TEST_BUTTON = ("push UI: the bell's OS checkbox on, Test subscribes through the (stubbed) PushManager, PUT "
                  "/push/subscription 200, says push is on, and the row is in SQL")
UI_SW_SHOW = ("push UI: the plaintext the relay pushed to the browser's subscription, delivered to the real "
              "service worker (CDP), is shown: registration.getNotifications() holds its tag")


def _leaks_scope() -> None:
    import push_scope

    real = push_scope.accounts_for

    async def accounts_for(kind, principal_id, issued_ms):
        got = await real(kind, principal_id, issued_ms)
        return None if got is None else await push_scope.live_accounts()

    push_scope.accounts_for = accounts_for


def _forgets_sent() -> None:
    import push_decide as pd

    pd.Seen.has = lambda self, tag, now: False


def _keeps_gone() -> None:
    import push_decide as pd

    real = pd.outcome
    pd.outcome = lambda status: "fail" if status in (404, 410) else real(status)


def _ignores_types() -> None:
    import push_decide as pd

    pd.wanted = lambda sub, notice, platform: True


def register(Fault) -> dict:
    return {
        "push-leaks-scope": Fault(_leaks_scope, (PUSH_SCOPE,)),
        "push-forgets-sent": Fault(_forgets_sent, (PUSH_NO_REPUSH,)),
        "push-keeps-gone": Fault(_keeps_gone, (PUSH_PRUNED_GONE,)),
        "push-ignores-types": Fault(_ignores_types, (PUSH_TYPES,)),
    }
