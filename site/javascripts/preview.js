/* Click-to-preview overlay for icon tiles.
   Keeps the tile a real link (middle-click / ctrl-click still open the SVG),
   but a plain click opens a dismissible preview instead of navigating away. */

(function () {
  var overlay, imgEl, titleEl, descEl, openEl, dlEl, lastFocus;

  function build() {
    overlay = document.createElement('div');
    overlay.className = 'aws-modal';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-label', 'Icon preview');
    overlay.hidden = true;
    overlay.innerHTML = [
      '<div class="aws-modal-box" role="document">',
      '  <button class="aws-modal-close" type="button" aria-label="Close preview">&times;</button>',
      '  <div class="aws-modal-stage"><img alt=""></div>',
      '  <h3 class="aws-modal-title"></h3>',
      '  <p class="aws-modal-desc"></p>',
      '  <div class="aws-modal-actions">',
      '    <a class="aws-modal-btn" target="_blank" rel="noopener">Open SVG</a>',
      '    <a class="aws-modal-btn" download>Download</a>',
      '    <button class="aws-modal-btn aws-modal-dismiss" type="button">Close</button>',
      '  </div>',
      '  <p class="aws-modal-hint">Press <kbd>Esc</kbd> or click outside to close.</p>',
      '</div>'
    ].join('\n');
    document.body.appendChild(overlay);

    imgEl = overlay.querySelector('.aws-modal-stage img');
    titleEl = overlay.querySelector('.aws-modal-title');
    descEl = overlay.querySelector('.aws-modal-desc');
    var btns = overlay.querySelectorAll('.aws-modal-actions a');
    openEl = btns[0];
    dlEl = btns[1];

    overlay.addEventListener('click', function (e) {
      if (e.target === overlay) close();
    });
    overlay.querySelector('.aws-modal-close').addEventListener('click', close);
    overlay.querySelector('.aws-modal-dismiss').addEventListener('click', close);
    document.addEventListener('keydown', function (e) {
      if (overlay.hidden) return;
      if (e.key === 'Escape') {
        e.preventDefault();
        close();
      } else if (e.key === 'Tab') {
        trap(e);
      }
    });
  }

  function focusable() {
    return Array.prototype.slice.call(
      overlay.querySelectorAll('button, a[href]')
    ).filter(function (el) { return el.offsetParent !== null; });
  }

  function trap(e) {
    var items = focusable();
    if (!items.length) return;
    var first = items[0];
    var last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }

  function open(tile) {
    var href = tile.getAttribute('href');
    var name = tile.dataset.title || tile.textContent.trim();
    var slug = tile.dataset.slug || '';

    imgEl.src = tile.href || href;
    imgEl.alt = name;
    titleEl.textContent = name;
    var desc = tile.dataset.desc || '';
    descEl.textContent = desc;
    descEl.hidden = !desc;
    openEl.href = tile.href || href;
    dlEl.href = tile.href || href;
    dlEl.setAttribute('download', slug ? slug + '.svg' : '');

    lastFocus = document.activeElement;
    overlay.hidden = false;
    document.body.classList.add('aws-modal-open');
    overlay.querySelector('.aws-modal-close').focus();
  }

  function close() {
    overlay.hidden = true;
    document.body.classList.remove('aws-modal-open');
    imgEl.removeAttribute('src');
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }

  function init() {
    if (!overlay) build();
    if (overlay.parentNode !== document.body) document.body.appendChild(overlay);
    close();

    var tiles = document.querySelectorAll('.aws-tile');
    Array.prototype.forEach.call(tiles, function (tile) {
      if (tile.dataset.awsBound) return;
      tile.dataset.awsBound = '1';
      tile.addEventListener('click', function (e) {
        // Let modified clicks behave like normal links.
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
        e.preventDefault();
        open(tile);
      });
    });
  }

  if (window.document$ && typeof window.document$.subscribe === 'function') {
    window.document$.subscribe(init);   // Material instant navigation
  } else if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
