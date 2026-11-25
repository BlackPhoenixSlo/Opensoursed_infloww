const menus = [...document.querySelectorAll("header details")];
for (const menu of menus) {
  menu.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || !menu.open) return;
    menu.open = false;
    menu.querySelector("summary").focus();
  });
  menu.addEventListener("focusout", (event) => {
    if (event.relatedTarget && !menu.contains(event.relatedTarget)) menu.open = false;
  });
}
document.addEventListener("click", (event) => {
  const link = event.target.closest("a");
  for (const menu of menus) if (menu.open && (!menu.contains(event.target) || link)) menu.open = false;
});

for (const button of document.querySelectorAll("[data-copy]")) {
  const target = document.querySelector(button.dataset.copy);
  const status = document.querySelector(button.dataset.status);
  if (!target || !status) continue;
  button.hidden = false;
  button.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(target.textContent.trim());
      status.textContent = "Copied to clipboard.";
    } catch {
      status.textContent = "Copy failed. Select the command and copy it manually.";
    }
    setTimeout(() => {
      status.textContent = "";
    }, 2500);
  });
}

for (const slider of document.querySelectorAll("[data-earnings-slider]")) {
  const rows = [...slider.querySelectorAll("tr[data-price]")];
  const range = slider.querySelector("[data-slider-range]");
  const count = slider.querySelector("[data-slider-count]");
  if (!range || !count || !rows.length) continue;
  const out = (name) => slider.querySelector(`[data-out="${name}"]`);
  const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
  const creators = () => {
    const n = Number.parseInt(count.value, 10);
    return Number.isFinite(n) ? Math.min(500, Math.max(1, n)) : 1;
  };
  const live = out("live");
  let liveTimer;
  const update = (announce = true) => {
    const index = Number(range.value);
    const row = rows[index];
    const price = Number(row.dataset.price);
    const n = creators();
    range.setAttribute("aria-valuetext", `${row.dataset.label}: Infloww ${usd.format(price)} per creator`);
    range.style.setProperty("--fill", `${(index / Math.max(1, rows.length - 1)) * 100}%`);
    out("bracket").textContent = row.dataset.label;
    out("price").textContent = usd.format(price);
    out("count").textContent = String(n);
    out("noun").textContent = n === 1 ? "creator" : "creators";
    out("year").textContent = usd.format(price * 12 * n);
    rows.forEach((r, i) => {
      r.toggleAttribute("data-active", i === index);
      if (i === index) r.setAttribute("aria-current", "true");
      else r.removeAttribute("aria-current");
    });
    if (!live || !announce) return;
    clearTimeout(liveTimer);
    liveTimer = setTimeout(() => {
      live.textContent = `Infloww ${usd.format(price)} per creator per month; ${n} for a year: ${usd.format(price * 12 * n)}.`;
    }, 400);
  };
  range.addEventListener("input", () => update());
  count.addEventListener("input", () => update());
  count.addEventListener("change", () => {
    count.value = String(creators());
    update();
  });
  slider.querySelector("[data-slider-fallback]").hidden = true;
  slider.querySelector("[data-slider-controls]").hidden = false;
  update(false);
}

for (const pre of document.querySelectorAll("pre")) {
  // Safari does not focus a scroller by itself: give overflowing code blocks a tab stop
  if (pre.scrollWidth > pre.clientWidth && !pre.hasAttribute("tabindex")) pre.tabIndex = 0;
}

for (const button of document.querySelectorAll("[data-reveal]")) {
  const input = document.getElementById(button.dataset.reveal);
  const label = button.querySelector("[data-reveal-label]");
  if (!input || !label) continue;
  button.hidden = false;
  button.addEventListener("click", () => {
    const show = input.type === "password";
    input.type = show ? "text" : "password";
    label.textContent = show ? "Hide" : "Show";
  });
}

for (const form of document.querySelectorAll("[data-auth-form]")) {
  const params = new URLSearchParams(location.hash.slice(1));
  const code = params.get("error");
  const errorBox = form.querySelector("#auth-error");
  if (code === null || !errorBox) continue;
  const messages = [...form.querySelectorAll("[data-auth-messages] [data-code]")];
  const match = messages.find((li) => li.dataset.code === code) || messages.find((li) => li.dataset.code === "");
  errorBox.textContent = match ? match.textContent : "";
  errorBox.hidden = false;
  const username = form.querySelector("#username");
  const password = form.querySelector("#password");
  if (username && params.get("username")) username.value = params.get("username");
  const retype = code === "taken" || code === "reserved" || !username?.value ? username : password;
  retype?.focus();
}

// a focused iframe scrolls the page to itself: load the demo only once a visitor has stopped on it
const demoFrame = document.querySelector("iframe[data-src]");
if (demoFrame) {
  let timer;
  let visible = false;
  const restartDwell = () => {
    clearTimeout(timer);
    if (!visible) return;
    timer = setTimeout(() => {
      demoFrame.src = demoFrame.dataset.src;
      observer.disconnect();
      window.removeEventListener("scroll", restartDwell);
    }, 400);
  };
  const observer = new IntersectionObserver(
    (entries) => {
      visible = entries.at(-1).intersectionRatio >= 0.2;
      restartDwell();
    },
    { threshold: 0.2 },
  );
  demoFrame.hidden = false;
  window.addEventListener("scroll", restartDwell, { passive: true });
  observer.observe(demoFrame);
}
