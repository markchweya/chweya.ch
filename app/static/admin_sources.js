/* Live crawl progress on the sources page.
 *
 * While any run is active the page asks the server for the latest counts
 * every two seconds and writes them into the run line of each source. The
 * numbers changing are the progress indicator; there is no spinner. When a
 * run finishes the page reloads once so the buttons come back and the
 * server renders the final state the same way it would on a fresh visit.
 */
(function () {
  "use strict";

  var cards = document.querySelectorAll("[data-source-id]");
  if (!cards.length) return;
  var anyActive = document.querySelector("[data-run-active='true']");
  if (!anyActive) return;

  var PHASE_WORDS = {
    crawling: "Crawling",
    indexing: "Indexing for keyword search",
    embedding: "Embedding passages",
    done: "Done"
  };

  function describe(run) {
    if (!run) return "Never crawled";
    if (run.active) {
      var head = PHASE_WORDS[run.phase] || run.phase;
      var parts = [head];
      if (run.phase === "crawling") {
        parts.push(run.fetched + " fetched");
        if (run.unchanged) parts.push(run.unchanged + " unchanged");
        if (run.versions) parts.push(run.versions + " new versions");
        if (run.failed) parts.push(run.failed + " failed");
        if (run.blocked) parts.push(run.blocked + " blocked");
      } else if (run.phase === "embedding") {
        parts.push(run.embedded + " passages embedded");
      }
      return parts.join(" · ");
    }
    var tail = [run.state];
    if (run.finished_at) tail.push(run.finished_at);
    if (run.state === "completed") {
      tail.push(run.fetched + " fetched");
      tail.push(run.versions + " new versions");
    } else if (run.error) {
      tail.push(run.error);
    }
    return tail.join(" · ");
  }

  function poll() {
    fetch("/admin/sources/progress", { headers: { Accept: "application/json" } })
      .then(function (response) { return response.ok ? response.json() : null; })
      .then(function (data) {
        if (!data) return;
        var stillActive = false;
        cards.forEach(function (card) {
          var run = data.runs[card.getAttribute("data-source-id")];
          var line = card.querySelector("[data-run]");
          if (line) line.textContent = describe(run);
          var wasActive = card.getAttribute("data-run-active") === "true";
          var isActive = !!(run && run.active);
          if (isActive) stillActive = true;
          if (wasActive && !isActive) {
            // Finished since the page loaded: show the final state the way
            // the server renders it, buttons included.
            window.location.reload();
          }
        });
        if (stillActive) window.setTimeout(poll, 2000);
      })
      .catch(function () { window.setTimeout(poll, 5000); });
  }

  window.setTimeout(poll, 2000);
})();
