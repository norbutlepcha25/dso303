/* DSO303 instructor playbook: shared behaviour for every HTML lesson plan.
   Guide: lesson-templates/README.md.

   Markup it reads:
     <section class="page" id="x" data-title="..." data-minutes="20">  one module
     <div class="mcq" data-answer="1">  .q, button.opt x N, .why         instant-check question
     <div class="hunt">  span.ln[data-defect="why"] ...                   click-the-defect code
     <div class="task"><label><input type="checkbox"> ...                 saved checklist
   Copy buttons are added to every <pre>. State is kept per lesson in localStorage. */
(function () {
  "use strict";
  var KEY = "dso303-playbook:" + location.pathname;
  var state = load();
  function load() { try { return JSON.parse(localStorage.getItem(KEY)) || {}; } catch (e) { return {}; } }
  function save() { try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) { /* private mode */ } }

  var pages = [].slice.call(document.querySelectorAll("section.page"));
  var nav = document.querySelector("nav");
  if (!pages.length || !nav) return;

  /* ---- navigation ---- */
  pages.forEach(function (p, i) {
    var b = document.createElement("button");
    b.dataset.page = p.id;
    b.innerHTML = "<span>" + (i + 1) + ". " + (p.dataset.title || p.id) + "</span>" +
      (p.dataset.minutes ? "<small>" + p.dataset.minutes + "′</small>" : "");
    b.addEventListener("click", function () { show(i, true); });
    nav.insertBefore(b, nav.querySelector(".back"));
  });
  var buttons = [].slice.call(nav.querySelectorAll("button[data-page]"));
  state.done = state.done || {};
  function markDone() { buttons.forEach(function (b) { b.classList.toggle("done", !!state.done[b.dataset.page]); }); }

  // Module URLs are "#/build". The slash means no element id matches, so the
  // browser never scrolls past the header to the section. "#build" still works.
  var current = 0;
  function fromHash() {
    var id = location.hash.replace(/^#\/?/, "");
    return pages.findIndex(function (p) { return p.id === id; });
  }
  function show(i, scroll) {
    current = Math.max(0, Math.min(pages.length - 1, i));
    pages.forEach(function (p, j) { p.classList.toggle("active", j === current); });
    buttons.forEach(function (b, j) { b.classList.toggle("active", j === current); });
    if (location.hash !== "#/" + pages[current].id) history.replaceState(null, "", "#/" + pages[current].id);
    state.page = current; save(); paint();
    if (scroll) window.scrollTo({ top: 0, behavior: "smooth" });
  }
  var start = fromHash();
  if (start >= 0 && location.hash.charAt(1) !== "/") window.addEventListener("load", function () { window.scrollTo(0, 0); });
  window.addEventListener("hashchange", function () {
    var j = fromHash();
    if (j >= 0 && j !== current) show(j, true);
  });

  /* ---- lesson timer ---- */
  var runner = document.querySelector(".runner");
  var planned = pages.reduce(function (s, p) { return s + (+p.dataset.minutes || 0); }, 0);
  state.used = state.used || {};           // seconds used per module
  var running = false, tick = null, clock, label, total, playBtn;
  if (runner) {
    runner.innerHTML =
      '<button class="primary" data-act="play">Start</button>' +
      '<span class="clock">--:--</span>' +
      '<button data-act="back">Back</button><button data-act="next">Next</button>' +
      '<span class="label"></span><span class="total"></span>' +
      '<button data-act="theme" title="Switch light / dark mode"></button>' +
      '<button data-act="reset" title="Clear timer, checklists and answers">Reset</button>';
    clock = runner.querySelector(".clock"); label = runner.querySelector(".label");
    total = runner.querySelector(".total"); playBtn = runner.querySelector('[data-act="play"]');
    runner.addEventListener("click", function (e) {
      var a = e.target.dataset.act;
      if (a === "play") toggle();
      if (a === "next") step(1);
      if (a === "back") step(-1);
      if (a === "theme") setTheme(isDark() ? "light" : "dark");
      if (a === "reset" && confirm("Reset the timer, checklists and answers for this lesson?")) {
        state = { done: {}, used: {} }; save(); location.hash = ""; location.reload();
      }
    });
  }
  /* ---- light / dark mode (one choice for all playbooks; default follows the system) ---- */
  var THEME = "dso303-playbook-theme";
  function isDark() {
    var t = document.documentElement.dataset.theme;
    return t ? t === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  }
  function setTheme(t) {
    document.documentElement.dataset.theme = t;
    try { localStorage.setItem(THEME, t); } catch (e) { /* private mode */ }
    themeLabel();
  }
  function themeLabel() {
    var b = runner && runner.querySelector('[data-act="theme"]');
    if (b) b.textContent = isDark() ? "Light mode" : "Dark mode";
  }
  try { var saved = localStorage.getItem(THEME); if (saved) document.documentElement.dataset.theme = saved; } catch (e) { /* ignore */ }
  themeLabel();
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", themeLabel);

  function fmt(s) { var n = Math.abs(s), m = Math.floor(n / 60), r = n % 60; return (s < 0 ? "−" : "") + m + ":" + (r < 10 ? "0" : "") + r; }
  function paint() {
    markDone();
    if (!runner) return;
    var p = pages[current], mins = +p.dataset.minutes || 0, used = state.used[p.id] || 0;
    var left = mins * 60 - used;
    clock.textContent = mins ? fmt(left) : "--:--";
    clock.classList.toggle("warn", mins && left <= 120 && left >= 0);
    clock.classList.toggle("over", mins && left < 0);
    label.textContent = (current + 1) + "/" + pages.length + " · " + (p.dataset.title || p.id);
    var all = Object.keys(state.used).reduce(function (s, k) { return s + state.used[k]; }, 0);
    total.textContent = "Used " + Math.floor(all / 60) + " of " + planned + " min";
    playBtn.textContent = running ? "Pause" : "Start";
  }
  function toggle() {
    running = !running;
    clearInterval(tick);
    if (running) tick = setInterval(function () {
      var id = pages[current].id; state.used[id] = (state.used[id] || 0) + 1; save(); paint();
    }, 1000);
    paint();
  }
  function step(d) { state.done[pages[current].id] = true; show(current + d, true); }
  document.addEventListener("keydown", function (e) {
    if (/INPUT|TEXTAREA|SELECT/.test(e.target.tagName) || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === " " && runner) { e.preventDefault(); toggle(); }
    else if (e.key === "n" || e.key === "N") step(1);
    else if (e.key === "b" || e.key === "B") show(current - 1, true);
  });

  /* ---- copy buttons ---- */
  document.querySelectorAll("pre").forEach(function (pre) {
    var b = document.createElement("button");
    b.className = "copy"; b.type = "button"; b.textContent = "Copy";
    b.addEventListener("click", function () {
      var text = (pre.querySelector("code") || pre).innerText;
      navigator.clipboard.writeText(text).then(function () {
        b.textContent = "Copied"; setTimeout(function () { b.textContent = "Copy"; }, 1200);
      }, function () { alert("Clipboard blocked. Select the command and copy it manually."); });
    });
    pre.appendChild(b);
  });

  /* ---- saved checklists ---- */
  state.checks = state.checks || {};
  document.querySelectorAll('.task input[type="checkbox"]').forEach(function (c, i) {
    c.checked = !!state.checks[i];
    c.addEventListener("change", function () { state.checks[i] = c.checked; save(); });
  });

  /* ---- instant-check questions ---- */
  state.mcq = state.mcq || {};
  document.querySelectorAll(".mcq").forEach(function (q, qi) {
    var opts = [].slice.call(q.querySelectorAll("button.opt")), right = +q.dataset.answer;
    function answer(i) {
      q.classList.add("answered");
      opts[right].classList.add("right");
      if (i !== right) opts[i].classList.add("wrong");
      state.mcq[qi] = i; save(); score();
    }
    opts.forEach(function (o, i) {
      o.type = "button";
      o.addEventListener("click", function () { if (!q.classList.contains("answered")) answer(i); });
    });
    if (state.mcq[qi] !== undefined) answer(state.mcq[qi]);
  });
  function score() {
    pages.forEach(function (p) {
      var qs = p.querySelectorAll(".mcq"), out = p.querySelector(".mcq-score");
      if (!qs.length || !out) return;
      var done = 0, ok = 0;
      qs.forEach(function (q) {
        if (!q.classList.contains("answered")) return;
        done++; if (!q.querySelector(".opt.wrong")) ok++;
      });
      out.textContent = done ? ok + " / " + qs.length + " correct" : "";
    });
  }

  /* ---- defect hunt ---- */
  document.querySelectorAll(".hunt").forEach(function (h) {
    var lines = [].slice.call(h.querySelectorAll(".ln")), defects = lines.filter(function (l) { return l.dataset.defect; });
    var log = document.createElement("div"); log.className = "huntlog";
    log.innerHTML = '<span class="count"></span> <button class="action secondary" type="button">Reveal all</button><ol></ol>';
    h.after(log);
    var list = log.querySelector("ol"), count = log.querySelector(".count");
    function found(l) {
      if (l.classList.contains("hit")) return;
      l.classList.add("hit");
      var li = document.createElement("li");
      li.innerHTML = "<code></code> — " + l.dataset.defect;
      li.querySelector("code").textContent = l.textContent.trim();
      list.appendChild(li); update();
    }
    function update() { count.textContent = "Defects found: " + h.querySelectorAll(".ln.hit").length + " / " + defects.length; }
    lines.forEach(function (l) {
      l.addEventListener("click", function () {
        if (l.dataset.defect) found(l);
        else { l.classList.add("miss"); setTimeout(function () { l.classList.remove("miss"); }, 400); }
      });
    });
    log.querySelector("button").addEventListener("click", function () { defects.forEach(found); });
    update();
  });

  show(start >= 0 ? start : (state.page || 0), false);
  score();
})();
