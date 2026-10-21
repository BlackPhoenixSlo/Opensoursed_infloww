"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { ClockPause } = require("../lib/clock-pause");

function setup({ open = { clock_event_id: 7, account_id: "100" }, minutes = 30 } = {}) {
  const calls = [];
  let t = 0;
  let current = open;
  const blocker = { active: new Set(), next: 1 };
  const clock = new ClockPause({
    now: () => t,
    api: {
      status: async () => ({ open: current, auto_clock_out_minutes: minutes }),
      clockOut: async (id) => {
        calls.push(["out", id]);
        current = null;
        return true;
      },
      clockIn: async (aid) => {
        calls.push(["in", aid]);
        current = { clock_event_id: 8, account_id: aid };
        return true;
      },
    },
    blocker: {
      start: () => {
        const id = blocker.next++;
        blocker.active.add(id);
        return id;
      },
      stop: (id) => blocker.active.delete(id),
    },
  });
  return { clock, calls, blocker, advance: (ms) => (t += ms) };
}

test("holds the power-save blocker only while clocked in", async () => {
  const { clock, blocker } = setup();
  await clock.refresh();
  assert.equal(blocker.active.size, 1);
  await clock.refresh(); // no second blocker
  assert.equal(blocker.active.size, 1);
  clock.dispose();
  assert.equal(blocker.active.size, 0);
});

test("lock → clock out; back within the auto clock-out minutes → clock in again", async () => {
  const { clock, calls, blocker, advance } = setup();
  await clock.refresh();
  await clock.pause("lock");
  assert.deepEqual(calls, [["out", 7]]);
  assert.equal(blocker.active.size, 0); // the machine may sleep now
  await clock.pause("sleep"); // already paused: no second clock-out
  assert.deepEqual(calls, [["out", 7]]);
  advance(10 * 60000);
  await clock.resume("unlock");
  assert.deepEqual(calls, [["out", 7], ["in", "100"]]);
  assert.equal(blocker.active.size, 1);
});

test("away longer than the auto clock-out minutes → stays out", async () => {
  const { clock, calls, advance } = setup({ minutes: 30 });
  await clock.refresh();
  await clock.pause("sleep");
  advance(31 * 60000);
  await clock.resume("wake");
  assert.deepEqual(calls, [["out", 7]]);
});

test("not clocked in → nothing to pause or resume", async () => {
  const { clock, calls } = setup({ open: null });
  await clock.pause("lock");
  await clock.resume("unlock");
  assert.deepEqual(calls, []);
});

test("a failed clock-out leaves no pause behind", async () => {
  const { clock } = setup();
  clock.api.clockOut = async () => false;
  await clock.pause("lock");
  assert.equal(clock.paused, null);
});
