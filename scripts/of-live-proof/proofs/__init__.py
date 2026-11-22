"""Proof definitions, one module per Phase (`phase<N>.py`), plus fake-only `fixtures`; `ALL` maps proof id -> Proof.
`PENDING`: ids a Phase lists that have no definition yet (the driver parks them until their ticket adds them).
`ORDER`: the proof lists' run order inside each `proof_core.order_group` (ofm-not-yet ticket 101: the driver's, never
the caller's; Phase 6's spec "Proof order")."""
from proofs import fixtures, phase0, phase1, phase2, phase3, phase4, phase6

ALL = {p.id: p for p in (*phase0.PROOFS, *phase1.PROOFS, *phase2.PROOFS, *phase3.PROOFS, *phase3.WIRED_PROOFS,
                         *phase4.PROOFS, *phase6.PROOFS, *fixtures.PROOFS)}
PENDING = frozenset(phase6.IDS) - set(ALL)
ORDER = tuple(phase6.IDS)
