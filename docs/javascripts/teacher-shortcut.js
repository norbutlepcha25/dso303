/* Teacher shortcut: type "teach" anywhere on the site (outside a text field)
   to open the teaching area. There is no visible link, so students are not
   pointed to it. See lesson-templates/README.md. */

(function () {
  var WORD = 'teach';
  var TARGET = 'teach-5t27uuv8/index.html';

  // Resolve the site root from this script's own URL (.../javascripts/x.js),
  // so the shortcut works on every page and under any base path.
  var script = document.currentScript;
  var siteRoot = script ? new URL('../', script.src) : new URL('/', location.href);

  var typed = '';

  document.addEventListener('keydown', function (e) {
    var t = e.target;
    var tag = (t.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select' || t.isContentEditable) return;
    if (e.metaKey || e.ctrlKey || e.altKey || e.key.length !== 1) return;

    typed = (typed + e.key.toLowerCase()).slice(-WORD.length);
    if (typed === WORD) {
      typed = '';
      location.href = new URL(TARGET, siteRoot).href;
    }
  });
})();
