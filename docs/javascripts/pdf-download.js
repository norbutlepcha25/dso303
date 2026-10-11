/* "Download PDF" button for unit topic pages.

   CI renders every unit topic page to site/pdf/unit<N>/topic<M>.pdf (see
   utils/build_pdfs.py). This script adds a button above the page title that
   downloads that file. If the PDF does not exist - local `mkdocs serve`, or a
   CI run where PDF generation failed - the button falls back to the browser's
   print dialog, where students can choose "Save as PDF". */

(function () {
  // Pages that get a button: unit<N>/topic<M>.html
  var TOPIC_PAGE = /\/unit(\d+)\/topic(\d+)\.html$/;

  var ICON =
    '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 20h14v-2H5v2zM19 9h-4V3H9v6H5l7 7 7-7z"/></svg>';

  function fileName(title) {
    return (
      'DSO303 ' +
      title
        .replace(/[\\/:*?"<>|]+/g, '')
        .replace(/\s+/g, ' ')
        .trim() +
      '.pdf'
    );
  }

  // Printing from a dark-mode page would produce white text on white paper,
  // so switch to the light scheme for the duration of the print.
  var savedScheme = null;
  var openedDetails = [];

  function beforePrint() {
    savedScheme = document.body.getAttribute('data-md-color-scheme');
    if (savedScheme && savedScheme !== 'default') {
      document.body.setAttribute('data-md-color-scheme', 'default');
    }
    // Collapsible blocks would print closed; open them for the print.
    openedDetails = [];
    document.querySelectorAll('article details:not([open])').forEach(function (d) {
      d.setAttribute('open', '');
      openedDetails.push(d);
    });
  }

  function afterPrint() {
    if (savedScheme) document.body.setAttribute('data-md-color-scheme', savedScheme);
    openedDetails.forEach(function (d) { d.removeAttribute('open'); });
    openedDetails = [];
  }

  function setup() {
    var match = location.pathname.match(TOPIC_PAGE);
    var article = document.querySelector('article.md-content__inner');
    if (!match || !article || article.querySelector('.pdf-download')) return;

    var heading = article.querySelector('h1');
    var title = heading ? heading.textContent.replace(/¶$/, '').trim() : document.title;
    var pdfUrl = new URL('../pdf/unit' + match[1] + '/topic' + match[2] + '.pdf', location.href).href;

    var button = document.createElement('a');
    button.className = 'pdf-download md-button';
    button.href = pdfUrl;
    button.setAttribute('download', fileName(title));
    button.setAttribute('title', 'Download these notes as a PDF');
    button.innerHTML = ICON + '<span>Download PDF</span>';

    function usePrintFallback() {
      button.removeAttribute('download');
      button.href = '#';
      button.setAttribute('title', 'Open the print dialog, then choose "Save as PDF"');
      button.querySelector('span').textContent = 'Save as PDF';
      button.addEventListener('click', function (event) {
        event.preventDefault();
        window.print();
      });
    }

    if (location.protocol === 'file:') {
      usePrintFallback();
    } else {
      fetch(pdfUrl, { method: 'HEAD' })
        .then(function (response) { if (!response.ok) usePrintFallback(); })
        .catch(usePrintFallback);
    }

    article.insertBefore(button, article.firstChild);
  }

  window.addEventListener('beforeprint', beforePrint);
  window.addEventListener('afterprint', afterPrint);

  // Works with and without Material's instant navigation.
  if (window.document$ && typeof window.document$.subscribe === 'function') {
    window.document$.subscribe(setup);
  } else if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', setup);
  } else {
    setup();
  }
})();
