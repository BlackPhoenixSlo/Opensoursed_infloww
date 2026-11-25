from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Literal, NamedTuple

FOLD = 10
TOP_PAGES = 5
BOTTOM_PAGES = 1
PAGE = 100


class Step(NamedTuple):
    kind: Literal["folder", "desc", "asc"]
    offset: int
    list_id: int | None = None


class CollectPlan:
    def __init__(self, folders: Iterable[int], *, max_pages: int, page: int = PAGE,
                 fold: int = FOLD, top: int = TOP_PAGES, bottom: int = BOTTOM_PAGES) -> None:
        if top <= 0 and bottom <= 0:
            raise ValueError("a round must page All (top or bottom > 0)")
        self.folders: list[int] = list(dict.fromkeys(folders)) if fold > 0 else []
        self.max_pages, self.page = max_pages, page
        self.fold, self.top, self.bottom = fold, top, bottom
        self.ended = False
        self.gap = False
        self.all_pages = 0
        self._desc_off = self._asc_off = 0
        self._step = max(1, page - 1)
        self._last: dict[str, int | None] = {"desc": None, "asc": None}
        self._desc_ids: set[int] = set()
        self._asc_ids: set[int] = set()
        self._fi = 0
        self._folder: int | None = None
        self._folder_off = self._folder_pages = 0
        self._stage: Literal["fold", "top", "bottom"] = "fold"
        self._left = fold

    @property
    def walked(self) -> bool:
        return self.ended and not self.gap

    @property
    def capped(self) -> bool:
        return not self.ended and self.all_pages >= self.max_pages

    def _all_open(self) -> bool:
        return not self.ended and self.all_pages < self.max_pages

    def next(self) -> Step | None:
        while True:
            if self._stage == "fold":
                if self._folder is not None:
                    return Step("folder", self._folder_off, self._folder)
                if self._left > 0 and self._fi < len(self.folders):
                    self._folder, self._folder_off, self._folder_pages = self.folders[self._fi], 0, 0
                    self._fi += 1
                    self._left -= 1
                    continue
                self._stage, self._left = "top", self.top
            elif self._stage == "top":
                if self._left > 0 and self._all_open():
                    return Step("desc", self._desc_off)
                self._stage, self._left = "bottom", self.bottom
            else:
                if self._left > 0 and self._all_open():
                    return Step("asc", self._asc_off)
                if not self._all_open() and self._fi >= len(self.folders):
                    return None
                self._stage, self._left = "fold", self.fold

    def feed(self, step: Step, ids: Sequence[int], has_more: bool) -> None:
        if step.kind == "folder":
            self._folder_pages += 1
            if not ids or not has_more or self._folder_pages >= self.max_pages:
                self._folder = None
            else:
                self._folder_off += self.page
            return
        self.all_pages += 1
        self._left -= 1
        got = set(ids)
        last = self._last[step.kind]
        if last is not None and last not in got:
            self.gap = True
        self._last[step.kind] = ids[-1] if len(ids) >= self.page and self.page > 1 else None
        if step.kind == "desc":
            met = bool(got & self._asc_ids)
            self._desc_ids |= got
            self._desc_off += self._step
        else:
            met = bool(got & self._desc_ids)
            self._asc_ids |= got
            self._asc_off += self._step
        if met or not got or not has_more:
            self.ended = True

    def skip_folder(self) -> None:
        self._folder = None
