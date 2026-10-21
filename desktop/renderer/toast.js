"use strict";

// Toast stack (lib/toast-window.js). Renders what main sends with textContent
// only, never innerHTML: names and message text come from fans. Silent, like
// the native notifications: the page plays its own alert sounds.

const stack = document.getElementById("stack");

function card(c) {
  const el = document.createElement("div");
  el.className = "card";
  const title = document.createElement("div");
  title.className = "title";
  title.textContent = c.title || "Inflowwww";
  const body = document.createElement("div");
  body.className = "body";
  body.textContent = c.body || "";
  const close = document.createElement("button");
  close.className = "close";
  close.type = "button";
  close.textContent = "×";
  close.title = "Dismiss";
  close.addEventListener("click", (e) => {
    e.stopPropagation();
    window.fasttToast.dismiss(c.id);
  });
  el.addEventListener("click", () => window.fasttToast.open(c.id));
  el.append(title, body, close);
  return el;
}

window.fasttToast.onCards((cards) => {
  stack.replaceChildren(...cards.map(card));
});
