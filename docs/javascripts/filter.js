/* Live filter for the AWS service icon grids.
   Re-runs on every page load, including Material's instant navigation. */

(function () {
  function init() {
    var input = document.getElementById('aws-filter-input');
    var counter = document.getElementById('aws-filter-count');
    if (!input) return;

    var tiles = Array.prototype.slice.call(document.querySelectorAll('.aws-tile'));
    var total = tiles.length;

    // Each grid is preceded by its category heading strip and an <h2>.
    var sections = Array.prototype.slice.call(document.querySelectorAll('.aws-grid')).map(function (grid) {
      var parts = [grid];
      var node = grid.previousElementSibling;
      while (node && node.tagName !== 'H2') {
        parts.push(node);
        node = node.previousElementSibling;
      }
      if (node) parts.push(node);
      return {
        parts: parts,
        tiles: Array.prototype.slice.call(grid.querySelectorAll('.aws-tile'))
      };
    });

    function setCount(shown) {
      if (!counter) return;
      counter.textContent = shown === total
        ? total + ' icons'
        : shown + ' of ' + total + ' icons';
    }

    function apply() {
      var q = input.value.trim().toLowerCase();
      var shown = 0;

      tiles.forEach(function (tile) {
        var hit = !q || (tile.dataset.name || '').indexOf(q) !== -1;
        tile.classList.toggle('aws-hidden', !hit);
        if (hit) shown++;
      });

      sections.forEach(function (section) {
        var any = section.tiles.some(function (t) {
          return !t.classList.contains('aws-hidden');
        });
        section.parts.forEach(function (el) {
          el.classList.toggle('aws-hidden', !any);
        });
      });

      setCount(shown);
    }

    input.addEventListener('input', apply);
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        input.value = '';
        apply();
      }
    });

    // "/" focuses the filter, matching the muscle memory of the site search.
    document.addEventListener('keydown', function (e) {
      if (e.key === '/' && document.activeElement !== input) {
        e.preventDefault();
        input.focus();
      }
    });

    setCount(total);
  }

  if (window.document$ && typeof window.document$.subscribe === 'function') {
    window.document$.subscribe(init);   // Material instant navigation
  } else if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
