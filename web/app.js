/* Naukri Autopilot, control panel front end.
   Six pages behind a small history-API router. No build step. */

const $ = (id) => document.getElementById(id);
const PAGES = ["home", "captures", "history", "configuration", "guidelines", "about"];
const PATH_OF = {
  home: "/", captures: "/captures", history: "/history",
  configuration: "/configuration", guidelines: "/guidelines", about: "/about",
};

const state = {
  status: null,
  since: 0,        // job lines already pulled
  liveLines: [],
  jobRunning: false,
  busy: false,     // a schedule change is in flight
  page: "home",
};

const KIND_LABEL = {
  update: "running update",
  dry: "checking sign-in",
  apply: "applying to jobs",
  "apply-dry": "previewing jobs",
  login: "waiting for sign in",
};

/* plumbing ---------------------------------------------------------- */
async function api(path, opts) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  return res.json();
}

function toast(msg, bad = false) {
  const el = document.createElement("div");
  el.className = "toast" + (bad ? " bad" : "");
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 3800);
}

function ago(ts) {
  if (!ts) return null;
  const mins = Math.round((Date.now() - new Date(ts.replace(" ", "T")).getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const h = Math.round(mins / 60);
  return h < 48 ? `${h}h ago` : `${Math.round(h / 24)}d ago`;
}

// Quotes too, since some of this lands inside attributes (file names, titles).
const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/* icons --------------------------------------------------------------- */
/* One stroke set for the whole dashboard: 24 box, 1.6 stroke,
   round caps, so nothing looks heavier or lighter than its neighbours. */
const SW = 'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"';
const UI = {
  play:   `<svg ${SW}><path d="M7 4.5v15l12-7.5-12-7.5z" fill="currentColor" stroke="none"/></svg>`,
  arrow:  `<svg ${SW}><path d="M5 12h14M13 6l6 6-6 6"/></svg>`,
  cal:    `<svg ${SW}><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/></svg>`,
  clock:  `<svg ${SW}><circle cx="12" cy="12" r="9"/><path d="M12 7.5V12l3 1.8"/></svg>`,
  check:  `<svg ${SW}><circle cx="12" cy="12" r="9"/><path d="M8.5 12.3l2.4 2.4 4.6-4.9"/></svg>`,
  cross:  `<svg ${SW}><circle cx="12" cy="12" r="9"/><path d="M9 9l6 6M15 9l-6 6"/></svg>`,
  key:    `<svg ${SW}><circle cx="8" cy="15" r="4"/><path d="M10.8 12.2L20 3M17 6l3 3M14.5 8.5l2 2"/></svg>`,
  doc:    `<svg ${SW}><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5z"/><path d="M14 3v5h5"/></svg>`,
  pulse:  `<svg ${SW}><path d="M3 12h4l2.5-7 5 14L17 12h4"/></svg>`,
  chev:   `<svg ${SW}><path d="M6 9l6 6 6-6"/></svg>`,
  spin:   `<svg ${SW}><path d="M12 3a9 9 0 1 0 9 9"/></svg>`,
};

function paintIcons(root = document) {
  root.querySelectorAll("[data-ic]").forEach((el) => {
    if (el.dataset.painted === el.dataset.ic) return;
    el.innerHTML = UI[el.dataset.ic] || "";
    el.dataset.painted = el.dataset.ic;
  });
}

function stampToday() {
  const el = $("nav-today");
  if (el) el.textContent = new Date().toLocaleDateString(undefined,
    { weekday: "short", month: "short", day: "numeric" });
}

$("nav-toggle").addEventListener("click", () => {
  const d = $("nav-drawer");
  const open = !d.classList.contains("open");
  d.classList.toggle("open", open);
  $("nav-toggle").setAttribute("aria-expanded", String(open));
});
$("nav-drawer").addEventListener("click", (e) => {
  if (e.target.closest("a")) $("nav-drawer").classList.remove("open");
});

/* router ------------------------------------------------------------ */
function pageFromPath(path) {
  if (path === "/settings") return "configuration";   // old bookmarks
  return PAGES.find((p) => PATH_OF[p] === path) || "home";
}

function go(page, push = true) {
  state.page = page;
  PAGES.forEach((p) => {
    document.querySelector(`[data-page="${p}"]`).hidden = p !== page;
  });
  document.querySelectorAll(".nav-links a, .nav-drawer a").forEach((a) => {
    a.classList.toggle("active", a.dataset.nav === page);
  });
  if (push && location.pathname !== PATH_OF[page]) history.pushState({}, "", PATH_OF[page]);
  window.scrollTo(0, 0);
  applySiteMotion(document.querySelector(`[data-page="${page}"]`));

  // Only the visible page pays for its data.
  if (page === "home") { loadActivity(); loadHomeShots(); }
  if (page === "captures") loadShots();
  if (page === "history") loadHistory();
  if (page === "guidelines") { typewriter(); startSpy(); }
}

document.addEventListener("click", (e) => {
  const a = e.target.closest("a[data-link]");
  if (!a) return;
  e.preventDefault();
  go(pageFromPath(new URL(a.href).pathname));
});
window.addEventListener("popstate", () => go(pageFromPath(location.pathname), false));

/* theme ------------------------------------------------------------- */
function applyTheme(choice) {
  if (choice === "system") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", choice);
  try { localStorage.setItem("naukri-theme", choice); } catch (e) {}
  document.querySelectorAll("#theme-row button, #theme-row-home button").forEach((b) => {
    b.classList.toggle("active", b.dataset.theme === choice);
  });
}
$("theme-row-home").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (b) applyTheme(b.dataset.theme);
});
$("theme-row").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (b) applyTheme(b.dataset.theme);
});

/* status ------------------------------------------------------------ */
function stat(ic, tone, value, label, note) {
  return `
    <div class="d-stat">
      <span class="d-stat-ic is-${tone}" data-ic="${ic}"></span>
      <div>
        <div class="d-stat-value" title="${esc(value)}">${esc(value)}</div>
        <div class="d-stat-label">${esc(label)}</div>
        <div class="d-stat-note">${esc(note)}</div>
      </div>
    </div>`;
}

let dashMotionDone = false;

function renderStatus(s) {
  state.status = s;
  const ses = s.session, sc = s.schedule, lr = s.lastRun, r = s.resume;

  // Until setup is finished (or skipped), Home is the setup checklist instead
  // of a page of empty panels.
  const fresh = showSetup(s);
  $("dash").hidden = fresh;
  $("home-empty").hidden = !fresh;
  if (fresh) renderSetup(s);

  const cards = [];

  if (!ses.saved) cards.push(stat("key", "bad", "Not signed in", "Session", "Sign in once from here."));
  else if (lr.status === "expired") cards.push(stat("key", "bad", "Expired", "Session", "Sign in again and you are set."));
  else {
    const stale = ses.ageDays > 20;
    cards.push(stat("key", stale ? "warn" : "ok", stale ? "Ageing" : "Active", "Session",
      stale ? `${ses.ageDays} days old, sign in soon` : `${ses.ageDays} days old`));
  }

  cards.push(sc.installed
    ? stat("clock", "ok", `Every ${sc.hours}h`, "Schedule", s.nextRun ? `Next around ${s.nextRun.slice(5)}` : "First run soon")
    : stat("clock", "warn", "Paused", "Schedule", "Pick one in Configuration"));

  const when = lr.at ? ago(lr.at) : "Never";
  const LAST = {
    never:   ["pulse", "warn", "No runs yet"],
    ok:      ["check", "ok", `Worked, ${when}`],
    partial: ["pulse", "warn", `Partly, ${when}`],
    blocked: ["cross", "bad", `Blocked, ${when}`],
    expired: ["cross", "bad", `Locked out, ${when}`],
    failed:  ["cross", "bad", `Failed, ${when}`],
  }[lr.status] || ["pulse", "warn", when];
  cards.push(stat(LAST[0], LAST[1], LAST[2], "Last run", lr.at ? lr.at.slice(0, 16) : "Do one by hand first"));

  if (r.disabled) cards.push(stat("doc", "warn", "Off", "Resume", "Re-upload is switched off"));
  else if (r.name) cards.push(stat("doc", "ok", r.name, "Resume", `${r.kb} KB, goes up every run`));
  else cards.push(stat("doc", "bad", "Missing", "Resume", "Add a PDF to Resume/"));

  $("stat-row").innerHTML = cards.join("");
  // The 8s refresh rebuilds these cards, so only the first render animates in.
  if (!dashMotionDone && !fresh) {
    dashMotionDone = true;
    applySiteMotion($("dash"));
  }

  // Status facts
  const act = s.config.actions || {};
  const on = [act.resume && "resume", act.headline && "headline"].filter(Boolean);
  const hl = s.config.headlines || [];
  const facts = [
    ["Updates", on.length ? on.join(" + ") : "none switched on"],
    ["Interval", sc.installed ? `${sc.hours} hours` : "paused"],
    ["Next run", sc.installed ? (s.nextRun || "one interval from now") : "not scheduled"],
    ["Session age", ses.saved ? `${ses.ageDays} days` : "not signed in"],
    ["Next headline", act.headline && hl.length >= 2 ? `variant ${(s.config.headlineIndex || 0) + 1} of ${hl.length}` : "rotation off"],
    ["Start on login", s.autostart ? "on" : "off"],
  ];
  $("status-facts").innerHTML = facts
    .map(([k, v]) => `<div class="d-fact"><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join("");

  // Header line under the greeting
  $("dash-sub").textContent = lr.at
    ? (lr.status === "ok" || lr.status === "partial"
        ? `Your profile was refreshed ${ago(lr.at)}.`
        : `The last run did not go through (${ago(lr.at)}). Worth a look below.`)
    : "Do one run by hand and check Naukri says updated today.";

  paintIcons($("stat-row"));
  renderHeadline(s);
  renderControls(s);
  // Show the interval that is actually registered. Without this the control
  // only ever updates when you click it, so a reload sits on "Checking."
  // however the schedule is really set. Skipped while a change is in flight,
  // so a poll landing mid-save cannot undo what you just picked.
  if (!state.busy) syncSegmented(sc.installed ? sc.hours : 0);
  $("footer-tick").textContent = "updated " + new Date().toLocaleTimeString();
}

/* onboarding ------------------------------------------------------------ */
const ONBOARD_KEY = "naukri-onboarded";
let setupShown = false;     // this visit showed the checklist with work left
let scheduling = false;

function onboarded() {
  try { return localStorage.getItem(ONBOARD_KEY) === "1"; } catch (e) { return true; }
}
function markOnboarded() {
  try { localStorage.setItem(ONBOARD_KEY, "1"); } catch (e) {}
}

function setupSteps(s) {
  const lr = s.lastRun;
  return {
    resume: !!s.resume.name || !!s.resume.disabled,
    signin: s.session.saved && lr.status !== "expired",
    test: !!s.everWorked,
    schedule: !!s.schedule.installed,
  };
}

function showSetup(s) {
  if (onboarded()) return false;
  const d = setupSteps(s);
  const all = d.resume && d.signin && d.test && d.schedule;
  if (!all) { setupShown = true; return true; }
  // Everything is done. If they finished it just now, show the done card until
  // they move on; if they arrived already set up, never show it at all.
  if (setupShown) return true;
  markOnboarded();
  return false;
}

function renderSetup(s) {
  const d = setupSteps(s);
  const lr = s.lastRun;
  const running = state.jobRunning;
  const kind = state.jobKind;
  const all = d.resume && d.signin && d.test && d.schedule;

  $("e-setup").hidden = all;
  $("e-done").hidden = !all;
  $("setup-sub").textContent = all
    ? "That's everything. Nice work."
    : "Four quick things and your profile keeps itself fresh from then on.";
  if (all) return;

  const order = ["resume", "signin", "test", "schedule"];
  const current = order.findIndex((k) => !d[k]);

  const btn = (label, attr, primary = true) =>
    `<button class="${primary ? "d-run" : "d-ghost"}" ${attr}>${label}</button>`;
  const spin = (text) => `<span class="e-live"><span class="e-spin"></span>${esc(text)}</span>`;

  const steps = [];

  // 1. Resume
  steps.push({
    t: "Add your resume",
    d: d.resume
      ? (s.resume.disabled ? "Resume re-upload is switched off, so you can skip this one." : `Found ${s.resume.name}. Nice.`)
      : "Drop your resume PDF into the Resume folder. This goes green on its own.",
  });

  // 2. Sign in
  let signinD, signinAct = "";
  if (d.signin) signinD = "You're signed in.";
  else if (running && kind === "login") signinD = spin("Browser's open. Sign in over there, then come back.");
  else {
    signinD = lr.status === "expired"
      ? "Naukri logged you out. Happens now and then, just sign in again."
      : "A browser window opens. Log in like you normally would, OTP and all.";
    signinAct = btn("Sign in", "data-setup-login");
  }
  steps.push({ t: "Sign in to Naukri", d: signinD, act: signinAct });

  // 3. Test run
  let testD, testAct = "", testHint = "";
  if (d.test) {
    testD = lr.status === "partial"
      ? "It worked, though one part didn't. Worth a quick look in Captures."
      : "It worked. Open your Naukri profile and it should say updated today.";
  } else if (running && kind === "update") {
    testD = spin("Running now. Give it about a minute.");
  } else {
    testD = "Takes about a minute. It re-uploads your resume and saves a screenshot so you can see it happened.";
    testAct = btn(lr.status === "never" ? "Run it" : "Try again", "data-setup-run");
    if (lr.status === "blocked")
      testHint = "Naukri blocked that one. It happens sometimes, give it a few minutes and try again.";
    else if (lr.status === "failed")
      testHint = `That one didn't go through. The <a href="/captures" data-link>screenshot</a> usually shows why.`;
  }
  steps.push({ t: "Do a test run", d: testD, act: testAct, hint: testHint });

  // 4. Schedule
  let schedD, schedAct = "";
  if (d.schedule) schedD = `Runs every ${s.schedule.hours} hours.`;
  else {
    schedD = "How often should it run? Once a day is plenty.";
    schedAct = [12, 24, 48].map((h) =>
      `<button class="${h === 24 ? "d-run" : "d-ghost"}" data-setup-hours="${h}" ${scheduling ? "disabled" : ""}>
        Every ${h}h${h === 24 ? '<span class="e-rec">recommended</span>' : ""}</button>`).join("");
  }
  steps.push({ t: "Pick a schedule", d: schedD, act: schedAct });

  $("e-steps").innerHTML = steps.map((st, i) => {
    const done = d[order[i]];
    const locked = !done && i > current;
    const cls = ["e-step", done && "done", i === current && "current", locked && "locked"].filter(Boolean).join(" ");
    // Buttons only on the step you're on, and never while something is running.
    const act = i === current && st.act && !running ? `<div class="e-step-act">${st.act}</div>` : "";
    return `
      <li class="${cls}">
        <span class="e-step-n">${done ? "&#10003;" : i + 1}</span>
        <div>
          <div class="e-step-t">${esc(st.t)}</div>
          <div class="e-step-d">${st.d.startsWith("<span") ? st.d : esc(st.d)}</div>
          ${st.hint && i === current ? `<div class="e-hint">${st.hint}</div>` : ""}
          ${act}
        </div>
      </li>`;
  }).join("");
}

$("e-steps").addEventListener("click", async (e) => {
  if (e.target.closest("[data-setup-login]")) return run("login");
  if (e.target.closest("[data-setup-run]")) return run("update");
  const h = e.target.closest("[data-setup-hours]");
  if (h && !scheduling) {
    scheduling = true;
    renderSetup(state.status);
    const hours = Number(h.dataset.setupHours);
    const res = await api("/api/schedule", { method: "POST", body: JSON.stringify({ hours }) });
    scheduling = false;
    if (!res.ok) toast("Couldn't set the schedule. Try again, or do it from Configuration.", true);
    refreshStatus();
  }
});

$("btn-skip-setup").addEventListener("click", () => {
  markOnboarded();
  refreshStatus();
});
$("btn-setup-done").addEventListener("click", () => {
  markOnboarded();
  refreshStatus();
  loadActivity();
  loadHomeShots();
});

function renderHeadline(s) {
  let tone = "ok";
  let text;

  if (state.jobRunning) {
    tone = "busy";
    text = KIND_LABEL[s.job.kind] || "working";
  } else if (s.lastRun.status === "blocked") {
    tone = "bad"; text = "Blocked by bot detection";
  } else if (!s.session.saved || s.lastRun.status === "expired") {
    tone = "bad"; text = "Sign in needed";
  } else if (!Object.values(s.config.actions).some(Boolean)) {
    tone = "warn"; text = "Nothing enabled to run";
  } else if (!s.schedule.installed) {
    tone = "warn"; text = "Signed in, not scheduled";
  } else if (s.lastRun.status === "failed") {
    tone = "bad"; text = `Every ${s.schedule.hours}h, last run failed`;
  } else {
    text = `Armed, every ${s.schedule.hours}h`;
  }

  $("nav-dot").className = "dot " + tone;
  $("nav-label").textContent = text;
}

/* configuration: what to update ------------------------------------------ */
function renderControls(s) {
  const on = s.config.actions;

  $("switches").innerHTML = s.actions
    .map((a) => `
      <div class="switch ${on[a.key] ? "on" : "off"}" data-key="${a.key}"
           role="switch" tabindex="0" aria-checked="${!!on[a.key]}">
        <div class="switch-text">
          <div class="switch-label">${esc(a.label)}</div>
          <div class="switch-detail">${esc(a.detail)}</div>
          ${a.caveat ? `<div class="switch-caveat">${esc(a.caveat)}</div>` : ""}
        </div>
        <div class="switch-track"></div>
      </div>`)
    .join("");

  const sel = $("resume-select");
  if (document.activeElement !== sel) {
    sel.innerHTML = s.resumeChoices.length
      ? s.resumeChoices.map((n) => `<option value="${esc(n)}">${esc(n)}</option>`).join("")
      : `<option value="">No files in Resume/</option>`;
    const current = s.config.resume || (s.resume && s.resume.name);
    if (current && s.resumeChoices.includes(current)) sel.value = current;
  }
  sel.disabled = !on.resume || !s.resumeChoices.length;

  // Redrawing wipes edits, so leave the editor alone while it is in use.
  if (!editorDirty && !$("variants").contains(document.activeElement)) {
    drawVariants(s.config.headlines, s.config.headlineIndex, s.headlineMax);
  }
  updateVariantsNote();

  const sw = $("sw-autostart");
  if (!sw.dataset.busy) {
    sw.classList.toggle("on", !!s.autostart);
    sw.classList.toggle("off", !s.autostart);
    sw.setAttribute("aria-checked", String(!!s.autostart));
  }

  const autoApply = s.config.autoApply || {};
  const applySwitch = $("sw-autoapply");
  applySwitch.classList.toggle("on", !!autoApply.enabled);
  applySwitch.classList.toggle("off", !autoApply.enabled);
  applySwitch.setAttribute("aria-checked", String(!!autoApply.enabled));
  if (!autoApplyDirty && !["apply-titles", "apply-locations", "apply-exclude"].includes(document.activeElement.id)) {
    $("apply-titles").value = (autoApply.titles || []).join("\n");
    $("apply-locations").value = (autoApply.locations || []).join("\n");
    $("apply-exclude").value = (autoApply.exclude || []).join("\n");
    $("autoapply-note").textContent = "";
  }
}

async function saveConfig(patch, note) {
  const res = await api("/api/config", { method: "POST", body: JSON.stringify(patch) });
  toast(res.ok ? note : res.error || "Could not save.", !res.ok);
  refreshStatus();
}

function flipSwitch(el) {
  const turningOn = !el.classList.contains("on");
  el.classList.toggle("on", turningOn);
  el.classList.toggle("off", !turningOn);
  const label = el.querySelector(".switch-label").textContent;
  saveConfig({ actions: { [el.dataset.key]: turningOn } },
    `${label} ${turningOn ? "on" : "off"}.`);
}

$("switches").addEventListener("click", (e) => {
  const el = e.target.closest(".switch");
  if (el) flipSwitch(el);
});
$("switches").addEventListener("keydown", (e) => {
  if (e.key !== " " && e.key !== "Enter") return;
  const el = e.target.closest(".switch");
  if (!el) return;
  e.preventDefault();
  flipSwitch(el);
});
$("resume-select").addEventListener("change", (e) =>
  saveConfig({ resume: e.target.value }, `Using ${e.target.value}.`));

/* headline variants -------------------------------------------------- */
let editorDirty = false;

function drawVariants(list, nextIndex, max) {
  const items = list && list.length ? list : ["", ""];
  $("variants").innerHTML = items
    .map((text, i) => `
      <div class="variant" data-i="${i}">
        <div class="variant-head">
          <span class="variant-tag ${i === nextIndex ? "next" : ""}">
            Variant ${i + 1}${i === nextIndex ? " · next up" : ""}
          </span>
          <span class="variant-tools">
            <span class="variant-count">${text.length}/${max}</span>
            <button class="variant-del" title="Remove">&times;</button>
          </span>
        </div>
        <textarea rows="3" maxlength="${max}" placeholder="Headline text">${esc(text)}</textarea>
      </div>`)
    .join("");
}

function readVariants() {
  return [...document.querySelectorAll("#variants textarea")].map((t) => t.value);
}

function updateVariantsNote() {
  const n = readVariants().filter((v) => v.trim()).length;
  const note = $("variants-note");
  if (editorDirty) note.textContent = "Unsaved changes.";
  else if (n < 2) note.textContent = "Add at least two, it needs something to rotate between.";
  else note.textContent = `${n} variants, one per run.`;
}

$("variants").addEventListener("input", (e) => {
  if (e.target.tagName !== "TEXTAREA") return;
  editorDirty = true;
  const max = (state.status && state.status.headlineMax) || 250;
  const cnt = e.target.closest(".variant").querySelector(".variant-count");
  cnt.textContent = `${e.target.value.length}/${max}`;
  cnt.classList.toggle("over", e.target.value.length > max);
  updateVariantsNote();
});
$("variants").addEventListener("click", (e) => {
  if (!e.target.classList.contains("variant-del")) return;
  e.target.closest(".variant").remove();
  editorDirty = true;
  updateVariantsNote();
});
$("btn-add-variant").addEventListener("click", () => {
  const s = state.status || {};
  const slots = s.headlineSlots || 6;
  const current = readVariants();
  if (current.length >= slots) return toast(`${slots} variants is the cap.`, true);
  drawVariants([...current, ""], s.config ? s.config.headlineIndex : 0, s.headlineMax || 250);
  editorDirty = true;
  updateVariantsNote();
});
$("btn-save-variants").addEventListener("click", async () => {
  const list = readVariants().map((v) => v.trim()).filter(Boolean);
  if (list.length === 1)
    return toast("Either two or more, or none at all.", true);
  editorDirty = false;
  await saveConfig({ headlines: list },
    list.length ? `Saved ${list.length} variants.` : "Variants cleared.");
});

/* job applications --------------------------------------------------- */
let autoApplyDirty = false;
const autoApplyInputs = ["apply-titles", "apply-locations", "apply-exclude"];
autoApplyInputs.forEach((id) => $(id).addEventListener("input", () => {
  autoApplyDirty = true;
  $("autoapply-note").textContent = "Unsaved changes.";
}));

function readTerms(id) {
  return $(id).value.split(/[\n,]/).map((value) => value.trim()).filter(Boolean);
}

async function saveAutoApply(patch = {}) {
  const autoApply = {
    titles: readTerms("apply-titles"),
    locations: readTerms("apply-locations"),
    exclude: readTerms("apply-exclude"),
    ...patch,
  };
  if (autoApply.enabled && (!autoApply.titles.length || !autoApply.locations.length)) {
    return toast("Add at least one title and one location before enabling auto-apply.", true);
  }
  autoApplyDirty = false;
  const res = await api("/api/config", { method: "POST", body: JSON.stringify({ autoApply }) });
  toast(res.ok ? "Auto-apply settings saved." : res.error || "Could not save.", !res.ok);
  refreshStatus();
}

function toggleAutoApply() {
  const sw = $("sw-autoapply");
  saveAutoApply({ enabled: !sw.classList.contains("on") });
}
$("sw-autoapply").addEventListener("click", toggleAutoApply);
$("sw-autoapply").addEventListener("keydown", (event) => {
  if (event.key === " " || event.key === "Enter") { event.preventDefault(); toggleAutoApply(); }
});
$("btn-save-autoapply").addEventListener("click", () => saveAutoApply());

/* autostart ---------------------------------------------------------- */
async function toggleAutostart() {
  const sw = $("sw-autostart");
  const want = !sw.classList.contains("on");
  sw.dataset.busy = "1";
  sw.classList.toggle("on", want);
  sw.classList.toggle("off", !want);
  const r = await api("/api/autostart", { method: "POST", body: JSON.stringify({ on: want }) });
  delete sw.dataset.busy;
  toast(r.on ? "Dashboard will start on login." : "Auto start off.");
  refreshStatus();
}
$("sw-autostart").addEventListener("click", toggleAutostart);
$("sw-autostart").addEventListener("keydown", (e) => {
  if (e.key === " " || e.key === "Enter") { e.preventDefault(); toggleAutostart(); }
});

/* interval ------------------------------------------------------------ */
function syncSegmented(hours) {
  document.querySelectorAll("#segmented button").forEach((b) => {
    b.classList.toggle("active", Number(b.dataset.hours) === Number(hours));
    b.disabled = state.busy;
  });
  $("segmented-status").textContent = state.busy
    ? "Applying."
    : hours
    ? `Scheduled every ${hours} hours.`
    : "Paused, nothing runs automatically.";
}

$("segmented").addEventListener("click", async (e) => {
  const btn = e.target.closest("button");
  if (!btn || state.busy) return;
  const hours = Number(btn.dataset.hours);
  state.busy = true;
  syncSegmented(hours);
  const res = await api("/api/schedule", { method: "POST", body: JSON.stringify({ hours }) });
  state.busy = false;
  toast(res.ok ? (hours ? `Scheduled every ${hours}h.` : "Schedule paused.")
               : "Could not change the schedule.", !res.ok);
  refreshStatus();
});

/* console -------------------------------------------------------------- */
function classify(line) {
  if (/ERROR|RUN FAILED|Traceback|failed:/i.test(line)) return "l-err";
  if (/WARNING/i.test(line)) return "l-warn";
  if (/RUN OK|LOGIN OK|Session saved|re-uploaded|verified/i.test(line)) return "l-ok";
  return "";
}

function paint(el, lines, emptyText) {
  const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  if (!lines.length) el.textContent = emptyText;
  else
    el.innerHTML = lines
      .map((l) => {
        const c = classify(l);
        return c ? `<span class="${c}">${esc(l)}</span>` : esc(l);
      })
      .join("\n");
  if (atBottom) el.scrollTop = el.scrollHeight;
}

async function pollJob() {
  let j;
  try { j = await api(`/api/job?since=${state.since}`); }
  catch (e) { return false; }   // server gone; the status poll says so
  if (j.lines && j.lines.length) {
    state.liveLines.push(...j.lines);
    state.since = j.total;
  }
  const wasRunning = state.jobRunning;
  state.jobRunning = j.running;
  state.jobKind = j.kind;
  // The setup checklist shows live progress, so redraw it when a job starts.
  if (!wasRunning && j.running && state.status && !$("home-empty").hidden) renderSetup(state.status);

  $("btn-stop").hidden = !j.running;
  ["btn-dry", "btn-login", "btn-apply-preview", "btn-apply"].forEach((id) => ($(id).disabled = j.running));
  const run = $("btn-run");
  $("console-dot").className = "dot " + (j.running ? "busy" : j.exitCode === null ? "" : j.exitCode === 0 ? "ok" : "bad");
  run.disabled = j.running;
  run.classList.toggle("running", j.running);
  const ic = run.querySelector(".d-pill-ic");
  ic.dataset.ic = j.running ? "spin" : "play";
  paintIcons(run);
  run.querySelector(".d-run-label").textContent = j.running
    ? KIND_LABEL[j.kind] || "working"
    : "Run update";

  $("console-title").textContent = j.running
    ? KIND_LABEL[j.kind] || "running"
    : j.exitCode === null
    ? "idle"
    : `${j.kind} finished, exit ${j.exitCode}`;
  paint($("console-out"), state.liveLines, "Nothing running. Hit “Run update” to kick one off.");

  if (wasRunning && !j.running) {
    const good = j.exitCode === 0;
    toast(good ? "All done." : `Run exited with code ${j.exitCode}.`, !good);
    refreshStatus();
    if (state.page === "home") { loadActivity(); loadHomeShots(); }
    if (state.page === "captures") loadShots();
    if (state.page === "history") loadHistory();
  }
  return j.running;
}

/* actions -------------------------------------------------------------- */
async function run(kind) {
  state.liveLines = [];
  state.since = 0;
  paint($("console-out"), [], "Starting.");
  $("console-box").open = true;
  const res = await api("/api/run", { method: "POST", body: JSON.stringify({ kind }) });
  if (!res.ok) return toast(res.error || "Could not start.", true);
  if (kind === "login") toast("Opening a browser window. Sign in over there.");
  pollJob();
}

$("btn-run").addEventListener("click", () => run("update"));
$("btn-dry").addEventListener("click", () => run("dry"));
$("btn-apply-preview").addEventListener("click", () => run("apply-dry"));
$("btn-apply").addEventListener("click", () => run("apply"));
$("btn-login").addEventListener("click", () => run("login"));
$("btn-stop").addEventListener("click", async () => {
  await api("/api/stop", { method: "POST" });
  toast("Stop signal sent.");
});

/* history --------------------------------------------------------------- */
async function loadHistory() {
  const r = await api("/api/logs?n=1000");
  paint($("history-out"), r.lines, "No runs yet.");
  const count = (re) => r.lines.filter((l) => re.test(l)).length;
  const stats = [
    ["Successful", count(/RUN OK/)],
    ["Failed", count(/RUN FAILED/)],
    ["Blocked", count(/Access Denied page/)],
    ["Sign-ins", count(/LOGIN OK/)],
  ];
  $("tally").innerHTML = stats
    .map(([label, n]) => `<div class="tally-item"><span class="tally-num">${n}</span>
      <span class="tally-label">${label}</span></div>`)
    .join("");
}
$("btn-refresh-log").addEventListener("click", loadHistory);

/* captures -------------------------------------------------------------- */
async function loadShots() {
  const r = await api("/api/screenshots");
  const grid = $("shots-grid");
  if (!r.items.length) {
    grid.innerHTML = `<div class="empty">Nothing here yet. Screenshots show up after the first run.</div>`;
    return;
  }
  grid.innerHTML = r.items
    .map((s) => `
      <figure class="shot" data-src="/screenshots/${encodeURIComponent(s.name)}" data-name="${esc(s.name)}">
        <input class="shot-pick" type="checkbox" value="${esc(s.name)}" />
        <img src="/screenshots/${encodeURIComponent(s.name)}" alt="" loading="lazy" />
        <figcaption class="shot-meta">
          <span>${esc(s.at)}</span>
          <span class="badge ${s.failed ? "bad" : "ok"}">${s.failed ? "failure" : "proof"}</span>
        </figcaption>
      </figure>`)
    .join("");
}

function syncShotStates() {
  document.querySelectorAll(".shot").forEach((f) =>
    f.classList.toggle("sel", f.querySelector(".shot-pick").checked));
}

$("shots-grid").addEventListener("click", (e) => {
  // The tickbox is for selecting, so it must not also open the lightbox.
  if (e.target.classList.contains("shot-pick")) return;
  const fig = e.target.closest(".shot");
  if (!fig) return;
  $("lightbox-img").src = fig.dataset.src;
  $("lightbox").hidden = false;
});
$("shots-grid").addEventListener("change", syncShotStates);
$("shots-all").addEventListener("change", (e) => {
  document.querySelectorAll(".shot-pick").forEach((c) => (c.checked = e.target.checked));
  syncShotStates();
});
$("btn-del-shots").addEventListener("click", async () => {
  const names = [...document.querySelectorAll(".shot-pick:checked")].map((c) => c.value);
  if (!names.length) return toast("Nothing selected.", true);
  if (!confirm(`Delete ${names.length} capture${names.length > 1 ? "s" : ""}?\n\nThis cannot be undone.`)) return;
  const r = await api("/api/screenshots/delete", {
    method: "POST", body: JSON.stringify({ names }),
  });
  toast(r.ok ? `Deleted ${r.deleted}.` : r.error || "Failed.", !r.ok);
  $("shots-all").checked = false;
  loadShots();
});

$("lightbox").addEventListener("click", () => ($("lightbox").hidden = true));
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") $("lightbox").hidden = true;
});

/* guide: copy the AI prompt ----------------------------------------------- */
$("btn-copy-prompt").addEventListener("click", async () => {
  const text = $("ai-prompt-text").textContent;
  let ok = false;
  try { await navigator.clipboard.writeText(text); ok = true; } catch (e) {
    // Older browsers: select a hidden textarea and copy that.
    const t = document.createElement("textarea");
    t.value = text; t.style.position = "fixed"; t.style.opacity = "0";
    document.body.appendChild(t); t.select();
    try { ok = document.execCommand("copy"); } catch (e2) {}
    t.remove();
  }
  const b = $("btn-copy-prompt");
  b.textContent = ok ? "Copied" : "Select and copy it";
  setTimeout(() => { b.textContent = "Copy"; }, 1800);
});

/* first run ----------------------------------------------------------- */
/* The guide is not in the nav, so point people at it once and then leave
   them alone. It stays reachable from Configuration forever. */
const SEEN_KEY = "naukri-seen-guide";

function seenGuide() {
  try { return localStorage.getItem(SEEN_KEY) === "1"; } catch (e) { return true; }
}
function markGuideSeen() {
  // Unticking the box is how you ask to be reminded next time.
  const box = document.getElementById("modal-dontshow");
  if (box && !box.checked) return;
  try { localStorage.setItem(SEEN_KEY, "1"); } catch (e) {}
}
function closeModal() {
  const m = $("modal");
  m.hidden = true;
  m.innerHTML = "";
}

function showFirstRunModal() {
  const m = $("modal");
  m.innerHTML = `
    <div class="modal-card" role="dialog" aria-modal="true" aria-label="Welcome to Naukri Autopilot for Windows">
      <button class="modal-x" data-close aria-label="Close">&times;</button>
      <h3>Hello &#128075;</h3>
      <p>
        This keeps your Naukri profile looking fresh so recruiters keep finding
        you. Sign in once, pick how often it runs, and it quietly does the rest.
      </p>
      <p class="modal-soft">
        Want a quick tour first? It takes five minutes, and you can always find
        it again in Configuration.
      </p>
      <p class="modal-soft">
        Rather have an AI set it up for you? The guide has a prompt you can
        paste into Claude, ChatGPT or whatever you use.
      </p>
      <label class="modal-check">
        <input type="checkbox" id="modal-dontshow" checked />
        Don't show this again
      </label>
      <div class="modal-actions">
        <button class="pill pill-quiet modal-cta" data-open-guide>Show me around</button>
        <button class="pill pill-quiet" data-close>I'm good</button>
      </div>
    </div>`;
  m.hidden = false;
}

$("modal").addEventListener("click", (e) => {
  if (e.target.closest("#modal-dontshow") || e.target.closest(".modal-check")) return;
  if (e.target.closest("[data-open-guide]")) {
    markGuideSeen();
    closeModal();
    go("guidelines");
    return;
  }
  if (e.target.id === "modal" || e.target.closest("[data-close]")) {
    markGuideSeen();
    closeModal();
  }
});

/* motion ---------------------------------------------------------------- */
/* Progressive: the reveal class is added by script, so if this never runs the
   pages still render fully, just without motion. */
const REDUCED = window.matchMedia("(prefers-reduced-motion: reduce)");

function reveal(scope) {
  if (REDUCED.matches || !scope) return;
  const targets = scope.querySelectorAll("[data-reveal]:not(.reveal)");
  if (!targets.length) return;
  const show = (el) => el.classList.add("in");

  targets.forEach((el, n) => {
    el.classList.add("reveal");
    if (n % 3 === 1) el.classList.add("d1");
    if (n % 3 === 2) el.classList.add("d2");
  });
  if (!("IntersectionObserver" in window)) { targets.forEach(show); return; }

  const io = new IntersectionObserver((entries) => {
    entries.forEach((en) => {
      if (!en.isIntersecting) return;
      show(en.target);
      io.unobserve(en.target);
    });
  }, { rootMargin: "0px 0px -6% 0px", threshold: 0.05 });
  targets.forEach((el) => io.observe(el));

  // Backstop: never let content depend on an observer firing.
  setTimeout(() => targets.forEach(show), 1200);
}

function applySiteMotion(scope) {
  if (REDUCED.matches || !scope) return;
  const selectors = [
    ".d-stat", ".d-panel", ".d-console", ".e-step",   // Home
    ".tally",                                         // History
    ".helpbox", ".setting-block",                     // Configuration
    ".guide-step",                                    // Guide
    ".about-lead", ".about-h", ".about p", ".about-foot",
  ];
  scope.querySelectorAll(selectors.join(", ")).forEach((el) => {
    if (!el.hasAttribute("data-reveal")) el.setAttribute("data-reveal", "");
  });
  reveal(scope);
}

/* guidelines: typewriter and scroll spy -------------------------------- */

let typed = false;
function typewriter() {
  const el = $("guide-type");
  if (!el || typed) return;
  typed = true;
  const text = el.textContent.trim();
  if (REDUCED.matches) { el.textContent = text; return; }
  const caret = document.createElement("span");
  caret.className = "type-caret";
  el.textContent = "";
  el.appendChild(caret);
  let n = 0;
  const tick = setInterval(() => {
    n += 1;
    caret.remove();
    el.textContent = text.slice(0, n);
    if (n >= text.length) { clearInterval(tick); return; }
    el.appendChild(caret);
  }, 18);
}

let spy = null;
function startSpy() {
  // IntersectionObserver does not fire on a hidden page, so this is wired up
  // when the guide actually becomes visible.
  if (spy) return;
  const links = [...document.querySelectorAll("#guide-toc a")];
  if (!links.length) return;
  spy = new IntersectionObserver((entries) => {
    entries.forEach((en) => {
      if (!en.isIntersecting) return;
      links.forEach((a) => a.classList.toggle("active", a.dataset.step === en.target.id));
    });
  }, { rootMargin: "-25% 0px -65% 0px" });
  document.querySelectorAll(".guide-step").forEach((el) => spy.observe(el));
}

/* home: activity chart ------------------------------------------------ */
let chartRange = "7d";
let chartRuns = [];

$("chart-range").addEventListener("click", (e) => {
  const b = e.target.closest("[data-range]");
  if (!b || b.dataset.range === chartRange) return;
  chartRange = b.dataset.range;
  document.querySelectorAll("#chart-range .d-chip").forEach((x) =>
    x.classList.toggle("active", x === b));
  loadActivity();
});

async function loadActivity() {
  try {
    const r = await api(`/api/activity?range=${chartRange}`);
    chartRuns = r.runs || [];
    drawChart(r.days);
    drawRecent();
    const label = { "7d": "7 days", "1m": "month", "3m": "3 months" }[chartRange];
    $("chart-sub").textContent = chartRuns.length
      ? `${r.ok} worked and ${r.failed} failed over the last ${label}. Each dot is the last run of that day, placed by the time it happened.`
      : `No runs in the last ${label} yet.`;
  } catch (e) { /* the status poll reports a dead server */ }
}

const SVGNS = "http://www.w3.org/2000/svg";
const OKS = new Set(["ok", "partial"]);

// Monotone cubic through the points (the same idea as d3's curveMonotoneX).
// It never swings back in time or overshoots a point, so two runs on the same
// day stay a clean vertical step and the line stays inside 00:00 to 24:00.
function smoothPath(pts) {
  const n = pts.length;
  const sec = [];
  for (let i = 0; i < n - 1; i++) {
    const h = pts[i + 1].cx - pts[i].cx;
    sec.push(h ? (pts[i + 1].cy - pts[i].cy) / h : 0);
  }
  const m = pts.map((p, i) => {
    if (i === 0) return sec[0];
    if (i === n - 1) return sec[n - 2];
    const s0 = sec[i - 1], s1 = sec[i];
    if (s0 * s1 <= 0) return 0;
    const h0 = p.cx - pts[i - 1].cx, h1 = pts[i + 1].cx - p.cx;
    const avg = h0 + h1 ? (s0 * h1 + s1 * h0) / (h0 + h1) : 0;
    return Math.sign(s0) * Math.min(Math.abs(s0), Math.abs(s1), Math.abs(avg) / 2);
  });
  let d = `M${pts[0].cx},${pts[0].cy}`;
  for (let i = 0; i < n - 1; i++) {
    const p1 = pts[i], p2 = pts[i + 1], t = (p2.cx - p1.cx) / 3;
    d += ` C${p1.cx + t},${p1.cy + m[i] * t} ${p2.cx - t},${p2.cy - m[i + 1] * t} ${p2.cx},${p2.cy}`;
  }
  return d;
}

function drawChart(days, animate = true) {
  const wrap = $("chart-wrap");
  wrap.innerHTML = "";
  const W = Math.max(320, wrap.clientWidth || 640), H = 280;
  const pad = { l: 46, r: 14, t: 14, b: 30 };
  const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b;

  const end = new Date(); end.setHours(0, 0, 0, 0);
  const start = new Date(end); start.setDate(end.getDate() - (days - 1));
  const dayMs = 86400000;
  const x = (d) => pad.l + ((d - start) / dayMs + 0.5) * (iw / days);
  const y = (mins) => pad.t + ih - (mins / 1440) * ih;  // 00:00 at the bottom, 24:00 on top

  const svg = document.createElementNS(SVGNS, "svg");
  svg.setAttribute("class", "d-chart");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("preserveAspectRatio", "none");
  const el = (tag, attrs, parent = svg) => {
    const n = document.createElementNS(SVGNS, tag);
    for (const k in attrs) n.setAttribute(k, attrs[k]);
    parent.appendChild(n);
    return n;
  };

  // Hour gridlines every 6 hours
  const grid = el("g", { class: "grid" });
  const yax = el("g", { class: "axis" });
  for (let h = 0; h <= 24; h += 6) {
    el("line", { x1: pad.l, x2: W - pad.r, y1: y(h * 60), y2: y(h * 60) }, grid);
    el("text", { x: pad.l - 8, y: y(h * 60) + 4, "text-anchor": "end" }, yax).textContent =
      `${String(h).padStart(2, "0")}:00`;
  }

  // Date labels, thinned so they never collide
  const xax = el("g", { class: "axis" });
  const step = days <= 7 ? 1 : days <= 31 ? 5 : 15;
  for (let i = 0; i < days; i += step) {
    const d = new Date(start.getTime() + i * dayMs);
    el("text", { x: x(d), y: H - 8, "text-anchor": "middle" }, xax).textContent =
      d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
  }

  // One dot per platform per day: that day's most recent run. Earlier runs
  // from the same day ride along in the tooltip.
  const days_ = new Map();
  chartRuns.forEach((r) => {
    const t = new Date(r.at.replace(" ", "T"));
    const k = `${r.platform || "naukri"}|${r.at.slice(0, 10)}`;
    if (!days_.has(k)) days_.set(k, []);
    days_.get(k).push({ r, t, ok: OKS.has(r.status) });
  });
  const pts = [...days_.values()].map((runs) => {
    runs.sort((a, b) => a.t - b.t);
    const last = runs[runs.length - 1];
    const day = new Date(last.t); day.setHours(0, 0, 0, 0);
    return { ...last, earlier: runs.slice(0, -1).reverse(),
             cx: x(day), cy: y(last.t.getHours() * 60 + last.t.getMinutes()) };
  }).sort((a, b) => a.t - b.t);

  // One dotted line per platform, joining its days in order. Only Naukri
  // today; the dots carry the outcome, the line just shows the rhythm.
  const byPlatform = new Map();
  pts.forEach((p) => {
    const k = p.r.platform || "naukri";
    if (!byPlatform.has(k)) byPlatform.set(k, []);
    byPlatform.get(k).push(p);
  });
  byPlatform.forEach((series, k) => {
    if (series.length > 1) {
      const ln = el("path", { class: "ln", "data-platform": k, d: smoothPath(series) });
      if (animate && !REDUCED.matches) ln.classList.add("draw");
    }
  });

  const STATUS = (run) => run.ok
    ? (run.r.status === "partial" ? "Partly worked" : "Worked")
    : ({ blocked: "Blocked", expired: "Session expired" }[run.r.status] || "Failed");
  const hhmm = (t) => t.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  const dot = (ok) => `<i style="background:var(${ok ? "--ok" : "--bad"})"></i>`;

  const tip = document.createElement("div");
  tip.className = "d-chart-tip";
  const r0 = days > 31 ? 2.6 : days > 7 ? 3.2 : 4;
  const dots = el("g", { class: "pts" });
  pts.forEach((p) => {
    const c = el("circle", { class: `pt ${p.ok ? "pt-ok" : "pt-bad"}`, cx: p.cx, cy: p.cy, r: r0 }, dots);
    // A bigger invisible target, so small dots are still easy to hover.
    const hit = el("circle", { class: "pt-hit", cx: p.cx, cy: p.cy, r: 11, tabindex: 0 }, dots);
    const show = () => {
      const bits = [];
      if (p.r.resume) bits.push(`resume ${p.r.resume}`);
      if (p.r.headline) bits.push(`headline ${p.r.headline}`);
      const prev = p.earlier.length ? `
        <div class="tip-prev">
          <div class="tip-dim">Earlier that day</div>
          ${p.earlier.map((e) => `<div class="tip-row"><span class="tip-status">${dot(e.ok)}${hhmm(e.t)}</span><span class="tip-dim">${STATUS(e)}</span></div>`).join("")}
        </div>` : "";
      tip.innerHTML = `
        <span class="tip-status">${dot(p.ok)}${STATUS(p)}</span><br/>
        <b>${p.t.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" })}</b>
        at ${hhmm(p.t)}<br/>
        <span class="tip-dim">${esc(bits.join(", ") || p.r.detail || "")}${p.r.seconds ? ` · ${p.r.seconds}s` : ""}</span>${prev}`;
      const box = wrap.getBoundingClientRect(), sb = svg.getBoundingClientRect();
      tip.classList.add("show");
      // Keep the tip inside the panel, so points at either edge do not push it
      // off the card or widen the page.
      const half = tip.offsetWidth / 2 + 4;
      const px = (p.cx / W) * sb.width + (sb.left - box.left);
      tip.style.left = `${Math.min(Math.max(px, half), box.width - half)}px`;
      tip.style.top = `${(p.cy / H) * sb.height + (sb.top - box.top)}px`;
      c.classList.add("hot");
    };
    const hide = () => { tip.classList.remove("show"); c.classList.remove("hot"); };
    hit.addEventListener("mouseenter", show);
    hit.addEventListener("focus", show);
    hit.addEventListener("mouseleave", hide);
    hit.addEventListener("blur", hide);
  });

  wrap.appendChild(svg);
  wrap.appendChild(tip);
  if (!pts.length) {
    const empty = document.createElement("div");
    empty.className = "d-chart-empty";
    empty.textContent = "Runs will show up here as dots, one per day, placed by the time they happened.";
    wrap.appendChild(empty);
  }
}

let resizeT;
window.addEventListener("resize", () => {
  clearTimeout(resizeT);
  resizeT = setTimeout(() => { if (state.page === "home" && !$("dash").hidden) drawChart({ "7d": 7, "1m": 30, "3m": 90 }[chartRange], false); }, 150);
});

/* home: recent activity and captures -------------------------------------- */
function drawRecent() {
  const recent = chartRuns.slice(-4).reverse();
  if (!recent.length) {
    $("activity-list").innerHTML = `<li class="d-empty-row">Nothing yet. Runs show up here as they happen.</li>`;
    return;
  }
  const TITLE = { ok: "Profile refreshed", partial: "Partly refreshed", failed: "Run failed",
                  blocked: "Blocked by Naukri", expired: "Session expired" };
  $("activity-list").innerHTML = recent.map((r) => {
    const ok = OKS.has(r.status);
    const parts = [];
    if (r.resume && r.resume !== "skip") parts.push(`resume ${r.resume === "yes" ? "uploaded" : "failed"}`);
    if (r.headline && r.headline !== "skip") parts.push(`headline ${r.headline === "yes" ? "rotated" : "failed"}`);
    return `
      <li class="d-act">
        <span class="d-act-ic ${ok ? "ok" : "bad"}" data-ic="${ok ? "check" : "cross"}"></span>
        <div><p class="d-act-title">${esc(TITLE[r.status] || "Run")}</p>
          <p class="d-act-detail">${esc(parts.join(", ") || r.detail || "")}</p></div>
        <span class="d-act-when">${esc(ago(r.at))}</span>
      </li>`;
  }).join("");
  paintIcons($("activity-list"));
}

async function loadHomeShots() {
  const r = await api("/api/screenshots");
  const items = (r.items || []).slice(0, 4);
  $("home-shots").innerHTML = items.length
    ? items.map((s) => `
        <a class="d-shot" href="/captures" data-link>
          <img src="/screenshots/${encodeURIComponent(s.name)}" alt="" loading="lazy" />
          <span><span>${esc(s.at.slice(5))}</span>${s.failed ? '<span class="bad">failure</span>' : "<span>proof</span>"}</span>
        </a>`).join("")
    : `<div class="d-empty-row">Screenshots show up here after the first run.</div>`;
}

/* boot ------------------------------------------------------------------ */
async function refreshStatus() {
  try {
    renderStatus(await api("/api/status"));
  } catch {
    $("nav-label").textContent = "Server unreachable";
    $("nav-dot").className = "dot bad";
  }
}

window.addEventListener("scroll", () => {
  document.querySelector(".nav").classList.toggle("scrolled", window.scrollY > 8);
});

let saved = "system";
try { saved = localStorage.getItem("naukri-theme") || "system"; } catch (e) {}
applyTheme(saved);

stampToday();
paintIcons();
go(pageFromPath(location.pathname), false);
refreshStatus();
if (!seenGuide()) showFirstRunModal();
pollJob();

// Nothing polls while the tab is in the background. Coming back catches up.
setInterval(() => { if (!document.hidden) pollJob(); }, 1200);
setInterval(() => { if (!document.hidden && !state.jobRunning) refreshStatus(); }, 8000);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) { pollJob(); refreshStatus(); }
});
