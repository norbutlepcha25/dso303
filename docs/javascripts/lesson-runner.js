/* Lesson runner for teacher pages (the docs/teach-... folder).

   Loaded only on pages flagged by hooks/teacher_pages.py (see
   overrides/main.html). A lesson is a Markdown page whose segments are
   level-2 headings carrying a duration:

       ## Hook: the college portal problem { data-minutes="15" }
       ## Break { data-minutes="10" .break }

   From those headings this script builds:
     - a sticky control bar: lesson clock, current segment, countdown,
       Back / Start-Pause / Next / Focus / Reset
     - a clickable timeline, proportional to each segment's duration
     - a scheduled time label under every segment heading
     - the schedule table, wherever the page contains
       <div class="lesson-schedule"></div>
   and it makes task-list checkboxes clickable and remembered.

   Focus mode hides the site header, tabs, sidebars and footer so the lesson
   fills the screen; all lesson content stays visible.

   Keys: Space start/pause, N next, B back, F focus mode, Esc leave focus mode.
   State is kept in this browser's localStorage, per lesson page. */

(function () {
  if (!document.querySelector('meta[name="dso303-page"][content="lesson"]')) return;
  var article = document.querySelector('article.md-content__inner');
  if (!article) return;

  var STORE = 'dso303-lesson:' + location.pathname;

  function load(key, fallback) {
    try {
      var raw = localStorage.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    } catch (e) {
      return fallback;
    }
  }

  function save(key, value) {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch (e) {
      /* private mode or storage full: the runner still works, it just forgets */
    }
  }

  enhanceChecklists();

  var headings = Array.prototype.slice.call(article.querySelectorAll('h2[data-minutes]'));
  if (!headings.length) return; // e.g. the lesson index page

  /* ---------- Segments ---------- */

  function headingText(h) {
    var text = '';
    h.childNodes.forEach(function (n) {
      if (!(n.nodeType === 1 && n.classList.contains('headerlink'))) text += n.textContent;
    });
    return text.trim();
  }

  var offset = 0;
  var segments = headings.map(function (h) {
    var minutes = parseFloat(h.getAttribute('data-minutes')) || 0;
    var seg = {
      el: h,
      title: headingText(h),
      minutes: minutes,
      start: offset,
      isBreak: h.classList.contains('break')
    };
    offset += minutes;
    return seg;
  });
  var plannedMinutes = offset;

  function clock(min) {
    var h = Math.floor(min / 60);
    var m = Math.round(min % 60);
    return (h < 10 ? '0' : '') + h + ':' + (m < 10 ? '0' : '') + m;
  }

  function mmss(ms) {
    var neg = ms < 0;
    var s = Math.floor(Math.abs(ms) / 1000);
    var m = Math.floor(s / 60);
    s = s % 60;
    return (neg ? '-' : '') + m + ':' + (s < 10 ? '0' : '') + s;
  }

  function hhmmss(ms) {
    var s = Math.floor(ms / 1000);
    var h = Math.floor(s / 3600);
    var m = Math.floor((s % 3600) / 60);
    s = s % 60;
    return h + ':' + (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s;
  }

  // Scheduled time under each heading.
  segments.forEach(function (seg) {
    var label = document.createElement('p');
    label.className = 'lr-seg-time';
    label.textContent =
      clock(seg.start) + '–' + clock(seg.start + seg.minutes) + ' · ' + seg.minutes + ' min';
    seg.el.insertAdjacentElement('afterend', label);
  });

  // Schedule table wherever the author asked for one.
  article.querySelectorAll('.lesson-schedule').forEach(function (slot) {
    var rows = segments
      .map(function (seg, i) {
        return (
          '<tr><td>' + clock(seg.start) + '–' + clock(seg.start + seg.minutes) + '</td>' +
          '<td>' + seg.minutes + ' min</td>' +
          '<td><a href="#' + seg.el.id + '" data-seg="' + i + '">' + escapeHtml(seg.title) + '</a></td></tr>'
        );
      })
      .join('');
    slot.innerHTML =
      '<table><thead><tr><th>Time</th><th>Duration</th><th>Segment</th></tr></thead>' +
      '<tbody>' + rows + '</tbody></table>' +
      '<p class="lr-total">Planned total: ' + plannedMinutes + ' minutes</p>';
  });

  function escapeHtml(s) {
    return s.replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  /* ---------- State ---------- */

  var state = load(STORE, null);
  if (!state || !Array.isArray(state.elapsed) || state.elapsed.length !== segments.length) {
    state = { index: 0, running: false, tickStart: null, elapsed: segments.map(function () { return 0; }) };
  }

  function now() { return Date.now(); }

  function segmentElapsed(i) {
    var e = state.elapsed[i] || 0;
    if (state.running && i === state.index && state.tickStart) e += now() - state.tickStart;
    return e;
  }

  function lessonElapsed() {
    var total = 0;
    for (var i = 0; i < segments.length; i++) total += segmentElapsed(i);
    return total;
  }

  function bank() {
    // Move running time into the current segment's total.
    if (state.running && state.tickStart) {
      state.elapsed[state.index] += now() - state.tickStart;
      state.tickStart = now();
    }
  }

  /* ---------- Control bar ---------- */

  var bar = document.createElement('div');
  bar.className = 'lesson-runner';
  bar.innerHTML =
    '<div class="lr-row">' +
    '  <div class="lr-clock" title="Lesson time used / planned"><span class="lr-elapsed">0:00:00</span>' +
    '    <small>/ ' + plannedMinutes + ' min</small></div>' +
    '  <div class="lr-current"><span class="lr-index"></span><span class="lr-title"></span></div>' +
    '  <div class="lr-countdown" title="Time left in this segment"></div>' +
    '  <div class="lr-buttons">' +
    '    <button type="button" data-act="back" title="Previous segment (B)">Back</button>' +
    '    <button type="button" data-act="toggle" class="lr-primary" title="Start or pause (Space)">Start</button>' +
    '    <button type="button" data-act="next" title="Next segment (N)">Next</button>' +
    '    <button type="button" data-act="focus" title="Focus mode: hide site menus (F)">Focus</button>' +
    '    <button type="button" data-act="reset" title="Reset the lesson timer">Reset</button>' +
    '  </div>' +
    '</div>' +
    '<div class="lr-timeline"></div>' +
    '<div class="lr-progress"><div class="lr-progress-fill"></div></div>';

  var timeline = bar.querySelector('.lr-timeline');
  segments.forEach(function (seg, i) {
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'lr-seg' + (seg.isBreak ? ' lr-break' : '');
    b.style.flexGrow = String(Math.max(seg.minutes, 1));
    b.title = clock(seg.start) + ' ' + seg.title + ' (' + seg.minutes + ' min)';
    b.setAttribute('data-seg', String(i));
    b.innerHTML = '<span>' + escapeHtml(seg.title) + '</span>';
    timeline.appendChild(b);
  });

  var h1 = article.querySelector('h1');
  if (h1) h1.insertAdjacentElement('afterend', bar);
  else article.insertBefore(bar, article.firstChild);


  var el = {
    elapsed: bar.querySelector('.lr-elapsed'),
    index: bar.querySelector('.lr-index'),
    title: bar.querySelector('.lr-title'),
    countdown: bar.querySelector('.lr-countdown'),
    toggle: bar.querySelector('[data-act="toggle"]'),
    fill: bar.querySelector('.lr-progress-fill'),
    segs: timeline.querySelectorAll('.lr-seg')
  };

  function render() {
    var seg = segments[state.index];
    var used = segmentElapsed(state.index);
    var left = seg.minutes * 60000 - used;

    el.elapsed.textContent = hhmmss(lessonElapsed());
    el.index.textContent = state.index + 1 + '/' + segments.length;
    el.title.textContent = seg.title;
    el.countdown.textContent = mmss(left);
    el.countdown.classList.toggle('lr-soon', left > 0 && left <= 120000);
    el.countdown.classList.toggle('lr-over', left <= 0);
    el.toggle.textContent = state.running ? 'Pause' : used > 0 ? 'Resume' : 'Start';
    el.fill.style.width = Math.min(100, (used / Math.max(seg.minutes * 60000, 1)) * 100) + '%';

    el.segs.forEach(function (b, i) {
      b.classList.toggle('lr-active', i === state.index);
      b.classList.toggle('lr-done', i < state.index);
    });
    segments.forEach(function (s, i) {
      s.el.classList.toggle('lr-current-seg', i === state.index);
    });
  }

  function go(i, scroll) {
    if (i < 0 || i >= segments.length) return;
    bank();
    state.index = i;
    if (state.running) state.tickStart = now();
    save(STORE, state);
    render();
    if (scroll !== false) segments[i].el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function toggle() {
    if (state.running) {
      bank();
      state.running = false;
      state.tickStart = null;
    } else {
      state.running = true;
      state.tickStart = now();
    }
    save(STORE, state);
    render();
  }

  function reset() {
    if (!confirm('Reset the lesson timer and go back to the first segment?')) return;
    state = { index: 0, running: false, tickStart: null, elapsed: segments.map(function () { return 0; }) };
    save(STORE, state);
    render();
    segments[0].el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function focus(on) {
    var root = document.documentElement;
    var enable = typeof on === 'boolean' ? on : !root.classList.contains('lesson-focus');
    root.classList.toggle('lesson-focus', enable);
    bar.querySelector('[data-act="focus"]').classList.toggle('lr-primary', enable);
  }

  bar.addEventListener('click', function (e) {
    var t = e.target.closest('button');
    if (!t) return;
    var act = t.getAttribute('data-act');
    if (act === 'back') go(state.index - 1);
    else if (act === 'next') go(state.index + 1);
    else if (act === 'toggle') toggle();
    else if (act === 'focus') focus();
    else if (act === 'reset') reset();
    else if (t.hasAttribute('data-seg')) go(parseInt(t.getAttribute('data-seg'), 10));
  });

  article.addEventListener('click', function (e) {
    var a = e.target.closest('.lesson-schedule a[data-seg]');
    if (a) {
      e.preventDefault();
      go(parseInt(a.getAttribute('data-seg'), 10));
    }
  });

  document.addEventListener('keydown', function (e) {
    var tag = (e.target.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || e.target.isContentEditable) return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === ' ') { e.preventDefault(); toggle(); }
    else if (e.key === 'n' || e.key === 'N') go(state.index + 1);
    else if (e.key === 'b' || e.key === 'B') go(state.index - 1);
    else if (e.key === 'f' || e.key === 'F') focus();
    else if (e.key === 'Escape') focus(false);
  });

  render();
  setInterval(render, 500);
  setInterval(function () { if (state.running) save(STORE, state); }, 5000);

  /* ---------- Checklists ---------- */

  function enhanceChecklists() {
    var key = STORE + ':checks';
    var checks = load(key, {});
    var boxes = article.querySelectorAll('.task-list-item input[type="checkbox"]');
    boxes.forEach(function (box, i) {
      box.disabled = false;
      if (checks[i] !== undefined) box.checked = !!checks[i];
      box.addEventListener('change', function () {
        checks[i] = box.checked;
        save(key, checks);
      });
    });
  }
})();
