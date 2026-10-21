"use strict";

// Sleep / lock awareness for the time-tracking clock.
//
// The relay has no paused state: an open Clock event counts until a clock-out
// or the inactivity sweep, which closes it at last activity + the Agency's
// auto clock-out minutes, so a laptop shut mid-shift is billed those minutes.
// Pausing is therefore a clock-out when the machine sleeps or the screen
// locks, and a clock-in on the same Creator when the user is back, but only
// within those auto clock-out minutes: longer than that and the sweep would
// have clocked them out anyway, so they clock in themselves.
//
// While clocked in it also holds a powerSaveBlocker('prevent-app-suspension')
// so idle sleep doesn't cut the live stream (and the notifications) mid-shift.
// Explicit sleep and lock still happen and pause the clock as above.
//
// `api` and `blocker` are injected; test/clock-pause.test.js drives it.

class ClockPause {
  /**
   * @param {object} o
   * @param {{status: () => Promise<any>, clockOut: (id:number) => Promise<boolean>, clockIn: (accountId:string|null) => Promise<boolean>}} o.api
   * @param {{start: () => any, stop: (id:any) => void}} o.blocker
   */
  constructor({ api, blocker, now = Date.now, log = () => {} }) {
    this.api = api;
    this.blocker = blocker;
    this.now = now;
    this.log = log;
    this.open = null; //     the open Clock event, from the last status read
    this.autoMinutes = 0;
    this.paused = null; //   { accountId, at } after we clocked out for a pause
    this.blockerId = null;
  }

  async refresh() {
    let st = null;
    try {
      st = await this.api.status();
    } catch {
      st = null;
    }
    if (st && typeof st === "object") {
      this.open = st.open && st.open.clock_event_id != null ? st.open : null;
      this.autoMinutes = Number(st.auto_clock_out_minutes) || 0;
    }
    // On a failed read keep what we knew; the next poll corrects it.
    this._syncBlocker();
  }

  async pause(reason) {
    if (this.paused) return;
    await this.refresh();
    const ev = this.open;
    if (!ev) return;
    let ok = false;
    try {
      ok = await this.api.clockOut(ev.clock_event_id);
    } catch {
      ok = false;
    }
    if (!ok) return; // the inactivity sweep still closes it, as before
    this.log(`[clock] paused (${reason}): clocked out of event ${ev.clock_event_id}`);
    this.paused = { accountId: ev.account_id ?? null, at: this.now() };
    this.open = null;
    this._syncBlocker();
  }

  async resume(reason) {
    const p = this.paused;
    this.paused = null;
    if (p && this.autoMinutes > 0 && this.now() - p.at < this.autoMinutes * 60000) {
      let ok = false;
      try {
        ok = await this.api.clockIn(p.accountId);
      } catch {
        ok = false;
      }
      this.log(`[clock] resume (${reason}): ${ok ? "clocked back in" : "clock-in refused"}`);
    } else if (p) {
      this.log(`[clock] resume (${reason}): away longer than auto clock-out, staying out`);
    }
    await this.refresh();
  }

  _syncBlocker() {
    if (this.open && this.blockerId == null) {
      this.blockerId = this.blocker.start();
    } else if (!this.open && this.blockerId != null) {
      this.blocker.stop(this.blockerId);
      this.blockerId = null;
    }
  }

  dispose() {
    this.open = null;
    this.paused = null;
    this._syncBlocker();
  }
}

module.exports = { ClockPause };
