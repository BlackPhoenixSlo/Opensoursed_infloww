import pytest

from slop.lib import procs


@pytest.mark.parametrize("root,kids,want", [
    (1, {}, [1]),
    (1, {1: [2, 3], 2: [4], 3: [5, 6]}, [4, 2, 5, 6, 3, 1]),
    (1, {1: [2], 2: [1]}, [2, 1]),
    (2, {1: [2], 2: [3], 9: [10]}, [3, 2]),
])
def test_tree_order_children_first(root, kids, want):
    assert procs.tree_order(root, kids) == want


def test_linux_proc_start_ticks(tmp_path, monkeypatch):
    (tmp_path / "123").mkdir()
    rest = " ".join(["S"] + [str(i) for i in range(4, 53)])
    (tmp_path / "123/stat").write_text(f"123 (a b) c) {rest}\n")
    monkeypatch.setattr(procs, "PROC", tmp_path)
    assert procs.start_time(123) == "ticks 22"
    assert procs.start_time(124) is None

