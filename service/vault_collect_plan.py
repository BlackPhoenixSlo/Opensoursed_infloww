"""service/vault_collect_plan.py — which OF page the manual Collect asks next. Pure.

The Collect (vault_ai_api._run_collect) walks OF the way the describe sweep ranks a
vault (vault_ai_vision_decide.priority_order), one fixed round repeated:

  a. the next FOLD folders in rail order, each paged whole (offset 0, 100, … until
     OF says no more; MAX_PAGES pages per folder at most)
  b. the next TOP_PAGES pages of All, newest first (sort desc)
  c. the next BOTTOM_PAGES pages of All, oldest first (sort asc)

The All walk is done ("walked") once either cursor reaches the end (an empty page or
hasMore false) or the two meet (a desc page holds an id the asc walk took, or the
reverse): between them they have seen the whole vault. Desc + asc pages together stop
at `max_pages` (the 20k-item backstop); stopped there unwalked, the walk is `capped`.
The plan ends when All is walked or capped and every folder is paged.

Usage: `step = plan.next()` (None = finished; asked twice it names the same page),
fetch it, then `plan.feed(step, ids, has_more)`; a folder page that failed:
`plan.skip_folder()` (the rest of that folder is dropped).
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Literal, NamedTuple

FOLD = 10          # folders per round
TOP_PAGES = 5      # desc pages per round (500 newest)
BOTTOM_PAGES = 1   # asc pages per round (100 oldest)


class Step(NamedTuple):
    kind: Literal["folder", "desc", "asc"]
    offset: int
    list_id: int | None = None


class CollectPlan:
    def __init__(self, folders: Iterable[int], *, max_pages: int, page: int = 100,
                 fold: int = FOLD, top: int = TOP_PAGES, bottom: int = BOTTOM_PAGES) -> None:
        if top <= 0 and bottom <= 0:
            raise ValueError("a round must page All (top or bottom > 0)")
        self.folders: list[int] = list(dict.fromkeys(folders)) if fold > 0 else []
        self.max_pages, self.page = max_pages, page
        self.fold, self.top, self.bottom = fold, top, bottom
        self.walked = False      # All seen end to end (a cursor hit the end, or they met)
        self.all_pages = 0       # desc + asc pages fed
        self._desc_off = self._asc_off = 0
        self._desc_ids: set[int] = set()
        self._asc_ids: set[int] = set()
        self._fi = 0                             # next folder to start
        self._folder: int | None = None          # folder being paged
        self._folder_off = self._folder_pages = 0
        self._stage: Literal["fold", "top", "bottom"] = "fold"
        self._left = fold                        # what the current stage still takes

    @property
    def capped(self) -> bool:
        """All stopped by the page backstop before it was walked."""
        return not self.walked and self.all_pages >= self.max_pages

    def _all_open(self) -> bool:
        return not self.walked and self.all_pages < self.max_pages

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
        """The page `step` named came back with media `ids`; OF said `has_more`."""
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
        if step.kind == "desc":
            met = bool(got & self._asc_ids)
            self._desc_ids |= got
            self._desc_off += self.page
        else:
            met = bool(got & self._desc_ids)
            self._asc_ids |= got
            self._asc_off += self.page
        if met or not got or not has_more:
            self.walked = True

    def skip_folder(self) -> None:
        """The folder being paged failed: drop the rest of it."""
        self._folder = None
