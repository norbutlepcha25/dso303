/* Practice and interview question pages: answers sit in collapsed
   "??? success" blocks under each question. This adds one button under the
   page title to open or close all of them (practice mode vs revision mode). */
(function () {
  function init() {
    if (!/\/(Questions|interviewquestions)\//.test(location.pathname)) return;
    var article = document.querySelector("article");
    var h1 = article && article.querySelector("h1");
    var blocks = article ? article.querySelectorAll("details.success") : [];
    if (!h1 || !blocks.length || article.querySelector(".answers-toggle")) return;

    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "md-button answers-toggle";
    function label() {
      var allOpen = [].every.call(blocks, function (d) { return d.open; });
      btn.textContent = allOpen ? "Collapse all answers" : "Expand all answers";
      return allOpen;
    }
    btn.addEventListener("click", function () {
      var open = !label();
      [].forEach.call(blocks, function (d) { d.open = open; });
      label();
    });
    [].forEach.call(blocks, function (d) { d.addEventListener("toggle", label); });
    label();

    var p = document.createElement("p");
    p.appendChild(btn);
    h1.after(p);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
