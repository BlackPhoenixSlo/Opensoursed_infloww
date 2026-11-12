import unittest
from slop.lib.latency_acceptance import latency_check, volume_knobs
from slop.lib.gate import exclusive

class Context:
    def __init__(self, users):
        self.users, self.checks, self.skips, self.metrics = users, [], [], {}
    def check(self, name, ok, **detail): self.checks.append((name, ok, detail))
    def skip(self, name, why): self.skips.append((name, why))
    def metric(self, name, value): self.metrics[name] = value

class Contract(unittest.TestCase):
    def run_check(self, users, values):
        ctx = Context(users)
        latency_check(ctx, 'latency', values, {k: 300 for k in values})
        return ctx
    def test_acceptance_boundary(self):
        self.assertTrue(self.run_check(120, {'send':700}).checks[0][1])
        self.assertFalse(self.run_check(120, {'send':700.01}).checks[0][1])
    def test_slow_action_cannot_hide(self):
        self.assertFalse(self.run_check(120, {'all':650, 'send':1100}).checks[0][1])
    def test_stretch_is_advisory(self):
        for value, met in ((500, True), (900, False)):
            ctx=self.run_check(200, {'send':value})
            self.assertEqual(ctx.checks, [])
            self.assertEqual(len(ctx.skips),1)
            self.assertEqual(ctx.metrics['latency_contract']['target_met'],met)
    def test_missing_nonfinite_is_failure(self):
        for value in (None, float('nan'), float('inf'),0):
            self.assertFalse(self.run_check(200, {'send':value}).checks[0][1])
    def test_small_remains_regression(self):
        self.assertFalse(self.run_check(20, {'send':500}).checks[0][1])
    def test_volume_selection(self):
        default=['--scale=medium','--users=200','--no-ui']
        self.assertIn('--users=120',volume_knobs('2026-11-05-relay-admission',default))
        self.assertIn('--users=120',volume_knobs('2026-11-01-vault-pro-20k',default))
        self.assertEqual(volume_knobs('unrelated',default),default)
    def test_acceptance_is_exclusive(self):
        self.assertTrue(exclusive(['--scale=medium','--users=120']))
        self.assertFalse(exclusive(['--scale=small','--users=120']))
        self.assertFalse(exclusive(['--scale=medium','--users=119']))

if __name__ == '__main__': unittest.main()
