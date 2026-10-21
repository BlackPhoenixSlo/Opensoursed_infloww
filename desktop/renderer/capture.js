"use strict";

// Capture-status UI. Talks to the main process only through window.fasttCapture
// (status-preload.js). Shows the four steps with the current one highlighted,
// one plain-language message, and the technical details folded away.

const steps = {
  app: document.getElementById("step-app"),
  of: document.getElementById("step-of"),
  msgs: document.getElementById("step-msgs"),
  save: document.getElementById("step-save"),
};
const appDetail = document.getElementById("step-app-detail");
const hint = document.getElementById("hint");
const diag = document.getElementById("diag");
const finishBtn = document.getElementById("finish");
const cancelBtn = document.getElementById("cancel");
const reopenBtn = document.getElementById("reopen");

function banner(kind, text) {
  hint.className = kind ? `banner ${kind}` : "banner";
  hint.textContent = text;
}

function render(s) {
  if (!s) return;
  const done = {
    app: s.appSignedIn === true,
    of: !!s.haveCookies,
    msgs: !!(s.haveHeaders && s.haveRules),
    save: s.status === "done",
  };
  const current = ["app", "of", "msgs", "save"].find((k) => !done[k]);
  for (const k of Object.keys(steps)) {
    const el = steps[k];
    el.classList.toggle("done", done[k]);
    el.classList.toggle("current", k === current);
    el.classList.toggle("blocked", k === current && (s.status === "error" || (k === "app" && s.appSignedIn !== null)));
    el.querySelector(".dot").textContent = done[k] ? "✓" : "";
  }

  if (s.appSignedIn === "unreachable") {
    appDetail.textContent = `Can't reach Inflowwww at ${s.appBase || "the server"}. Check it is running.`;
  } else if (s.appSignedIn === false) {
    appDetail.textContent = "You're not signed in. Sign in in the main window as the agency owner; you can do the OnlyFans steps meanwhile.";
  } else {
    appDetail.textContent = "in the main window, as the agency owner.";
  }

  if (s.status === "done") {
    banner("ok", `✓ Saved${s.savedAs ? ` (OnlyFans user ${s.savedAs})` : ""}. This window closes on its own.`);
  } else if (s.status === "sending") {
    banner("", "Saving to Inflowwww…");
  } else if (s.status === "error") {
    banner("err", `${s.error || "Saving failed."} Your OnlyFans sign-in is kept.`);
  } else if (s.ready && s.appSignedIn !== true) {
    banner("", "OnlyFans is captured. Sign in to Inflowwww in the main window and it saves on its own.");
  } else if (s.ready) {
    banner("", "Everything is captured. Saving…");
  } else if (s.appSignedIn === null) {
    banner("", "Checking that you're signed in to Inflowwww…");
  } else if (s.haveCookies) {
    banner("", "Signed in to OnlyFans. Now open your Messages there.");
  } else {
    banner("", "Sign in to OnlyFans in the other window. A Cloudflare check may appear first; give it a few seconds.");
  }

  finishBtn.textContent = s.status === "error" ? "Retry save" : "Save now";
  finishBtn.disabled = !(s.ready && s.appSignedIn === true && s.status !== "sending" && s.status !== "done");
  reopenBtn.disabled = s.status === "done";

  const d = s.diag || {};
  const lines = [
    s.detection ? `Browser profile: ${s.detection}` : "",
    `OnlyFans page: ${d.url || "not loaded yet"}${d.httpStatus != null ? ` (HTTP ${d.httpStatus})` : ""}`,
    s.userId ? `OnlyFans user id: ${s.userId}` : "",
    s.ofRev ? `x-of-rev: ${s.ofRev}` : "",
    d.lastRelayError ? `Last save reply: ${d.lastRelayError}` : "",
  ];
  diag.textContent = lines.filter(Boolean).join("\n");
}

finishBtn.addEventListener("click", () => window.fasttCapture?.finish());
cancelBtn.addEventListener("click", () => window.fasttCapture?.cancel());
reopenBtn.addEventListener("click", () => window.fasttCapture?.reopen());

if (window.fasttCapture) {
  window.fasttCapture.onState(render);
  window.fasttCapture.getState().then(render);
}
