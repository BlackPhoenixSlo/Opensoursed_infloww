import sys
import types

import pytest

from slop.lib import badge_faults as bf


def _register():
    return bf.register(lambda apply, targets: types.SimpleNamespace(apply=apply, targets=targets))


def test_fence_off_targets_stale_read_alone():
    from slop.lib.faults import FAULTS
    assert FAULTS["badge-ordering-fence-off"].targets == ("STALE_READ_NEVER_CLEARS",)


def test_fence_off_makes_newer_than_ask_always_false_and_teardown_restores(monkeypatch):
    def newer_than_ask(at, asked_at):
        return at > asked_at

    stub = types.SimpleNamespace(newer_than_ask=newer_than_ask)
    monkeypatch.setitem(sys.modules, "badge_reads_decide", stub)
    monkeypatch.setattr(stub, "newer_than_ask", newer_than_ask)
    _register()["badge-ordering-fence-off"].apply()
    assert stub.newer_than_ask(2.0, 1.0) is False
    assert stub.newer_than_ask(1.0, 1.0) is False
    monkeypatch.undo()
    assert stub.newer_than_ask is newer_than_ask


@pytest.mark.parametrize("module", [None, types.SimpleNamespace()], ids=["module-absent", "name-absent"])
def test_fence_off_without_the_name_raises_naming_phase_c(monkeypatch, module):
    monkeypatch.setitem(sys.modules, "badge_reads_decide", module)
    with pytest.raises(SystemExit, match="Phase C"):
        _register()["badge-ordering-fence-off"].apply()
