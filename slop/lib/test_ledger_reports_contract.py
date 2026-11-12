"""Deterministic acceptance-contract regressions; no server or gate required."""
import asyncio
import importlib.util
import inspect
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

SOURCE = Path(__file__).resolve().parents[1] / 'scenarios/2026-11-01-ledger-reports-volume.py'
spec = importlib.util.spec_from_file_location('ledger_contract', SOURCE)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class Context:
    users = 200

    def __init__(self):
        self.routes = {r: {'n': 20, 'p95_ms': b} for r, b in m.P95_MS.items()}
        self.probes = {r: m._probe_stats([(200, b)]) for r, b in m.P95_MS.items()}
        self.rec = SimpleNamespace(summary=lambda stage: self.routes)
        self.checks = {}

    def check(self, name, ok, **detail):
        self.checks[name] = 'PASS' if ok else 'FAIL'

    def skip(self, name, why, **detail):
        self.checks[name] = 'SKIP'

    def metric(self, *args):
        pass

    def verdict(self):
        # Also exercise the pre-fix harness in the explicit revert proof.
        args = (m.KNOWN_RED, self.probes) if 'parked' in inspect.signature(m._budgets).parameters else (self.probes,)
        m._budgets(self, *args)
        return list(self.checks.values())


class Contract(unittest.TestCase):
    def test_exact_budget_boundary_passes_six_independent_checks(self):
        self.assertEqual(Context().verdict(), ['PASS'] * 6)

    def test_each_crowd_budget_red_even_when_isolated_green(self):
        for route in m.P95_MS:
            with self.subTest(route=route):
                c = Context()
                c.routes[route]['p95_ms'] += .1
                self.assertEqual(c.verdict().count('FAIL'), 1)
                self.assertEqual(c.checks[m._budget_name(route)], 'FAIL')

    def test_each_probe_budget_red_even_when_crowd_green(self):
        for route in m.P95_MS:
            with self.subTest(route=route):
                c = Context()
                c.probes[route]['p95_ms'] += .1
                self.assertEqual(c.verdict().count('FAIL'), 1)
                self.assertEqual(c.checks[m._budget_name(route)], 'PASS')

    def test_missing_or_empty_crowd_fails(self):
        for route in m.P95_MS:
            for sample in (None, {}, {'n': 0, 'p95_ms': 0}, {'n': 1, 'p95_ms': None}):
                with self.subTest(route=route, sample=sample):
                    c = Context()
                    c.routes.pop(route)
                    if sample is not None:
                        c.routes[route] = sample
                    self.assertEqual(c.verdict().count('FAIL'), 1)
                    self.assertEqual(c.checks[m._budget_name(route)], 'FAIL')

    def test_missing_empty_error_or_inconsistent_probe_fails(self):
        for route in m.P95_MS:
            for probe in (None, {}, m._probe_stats([]), m._probe_stats([(500, 1)]),
                          m._probe_stats([(200, 1), (599, 1)]),
                          {'n': 1, 'ok': True, 'status': {500: 1}, 'p95_ms': 1},
                          {'n': 1, 'ok': True, 'status': {200: 1}, 'p95_ms': None}):
                with self.subTest(route=route, probe=probe):
                    c = Context()
                    c.probes.pop(route)
                    if probe is not None:
                        c.probes[route] = probe
                    self.assertEqual(c.verdict().count('FAIL'), 1)
                    self.assertNotIn('SKIP', c.checks.values())

    def test_no_evidence_fails_all_six(self):
        c = Context()
        c.routes.clear()
        c.probes.clear()
        self.assertEqual(c.verdict(), ['FAIL'] * 6)

    def test_historical_fast_measurements_do_not_fail_stale_or_waive_top(self):
        c = Context()
        for r, latency in zip(m.P95_MS, (1413.6, 282.5, 929.0)):
            c.routes[r]['p95_ms'] = latency
        for r, latency in zip(m.P95_MS, (145.6, 82.8, 128.3)):
            c.probes[r] = m._probe_stats([(200, latency)])
        self.assertEqual(c.verdict(), ['PASS', 'PASS', 'FAIL', 'PASS', 'PASS', 'PASS'])

    def test_thresholds_unchanged(self):
        expected = {m.FAN_ROUTE: 1500, m.TIPS_ROUTE: 800, m.TOP_ROUTE: 800}
        self.assertEqual(m.P95_MS, expected)
        self.assertEqual(getattr(m, 'PROBE_P95_MS', None), expected)


class Workload(unittest.IsolatedAsyncioTestCase):
    async def test_probes_exist_without_waiver_metadata(self):
        client = SimpleNamespace(aclose=AsyncMock(), prefix='')
        ctx = SimpleNamespace(owner=SimpleNamespace(share=lambda **kw: client), metric=lambda *a: None)
        win = m.Window(*([datetime(2026, 11, 10)] * 3))
        args = dict(w=None, http={}, big={'big'}, win=win, o_fans0={}, o_tips0=[])
        if 'parked' in inspect.signature(m._probes).parameters:
            args['parked'] = {}
        with patch.object(m, '_alone', AsyncMock(return_value=m._probe_stats([(200, 1)]))) as alone, \
             patch.object(m, '_timed', AsyncMock(return_value=(200, 1))) as timed, \
             patch.object(m, '_rows', return_value=[(10,)]):
            probes = await m._probes(ctx, **args)
        self.assertTrue(set(m.P95_MS) <= probes.keys())
        self.assertEqual(alone.await_count, 1)
        self.assertEqual(timed.await_count, 2)
        self.assertIn('account_id=big', timed.await_args_list[1].args[1])
        self.assertTrue(all(probes[r]['status'] == {200: 1} for r in m.P95_MS))

    async def test_big_creator_eligible_in_crowd_read_and_export(self):
        for export in (False, True):
            with self.subTest(export=export):
                stop = asyncio.Event()
                paths = []
                async def request(method, path, **kwargs):
                    paths.append(path)
                    stop.set()
                    return SimpleNamespace(status_code=200, headers={})
                rng = SimpleNamespace(uniform=lambda *a: 0, random=lambda: .95 if export else 0,
                                      choice=lambda xs: xs[0])
                args = dict(creators=['big', 'small'], fan_rows=[])
                if 'fan_pick' in m.Menu._fields:
                    args['fan_pick'] = ['small']
                pool = SimpleNamespace(request=request)
                await m._owner(pool=pool, export=pool, ag=0, menu=m.Menu(**args), windows=[{}],
                               stop=stop, rng=rng, scope=None)
                self.assertIn('account_id=big', paths[0])
                self.assertEqual('format=csv' in paths[0], export)


if __name__ == '__main__':
    unittest.main(verbosity=2)
