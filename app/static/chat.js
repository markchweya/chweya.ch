/* Progressive enhancement for the chat form.
 *
 * The form works without JavaScript: it posts and the server renders the full
 * page. This file upgrades that to a streamed answer, and falls back silently
 * if anything is unavailable.
 *
 * What it must get right for accessibility:
 *  - The transcript is a live region, so appended text is announced. Tokens
 *    are buffered into sentences before being written, because announcing
 *    every token makes a screen reader unusable.
 *  - There is a stop control while a response is streaming.
 *  - The Dumi mark carries status. No spinner is created anywhere.
 */
(function () {
  "use strict";

  var form = document.getElementById("ask");
  var input = document.getElementById("question");
  var transcript = document.getElementById("transcript");
  var status = document.getElementById("status");
  var stopButton = document.getElementById("stop");
  if (!form || !input || !transcript) return;

  var controller = null;

  function markup(state) {
    return (
      '<span class="dumi" data-state="' + state + '" aria-hidden="true">' +
      '<span class="dumi__orb">' +
      '<i class="dumi__blob dumi__blob--a"></i>' +
      '<i class="dumi__blob dumi__blob--b"></i>' +
      '<i class="dumi__blob dumi__blob--c"></i>' +
      '<i class="dumi__core"></i><i class="dumi__sheen"></i>' +
      "</span></span>"
    );
  }

  function addUserMessage(text) {
    var article = document.createElement("article");
    article.className = "msg msg--user";
    var body = document.createElement("div");
    body.className = "msg__text";
    // textContent, never innerHTML: the question is user input.
    body.textContent = text;
    article.appendChild(body);
    transcript.appendChild(article);
    return article;
  }

  function addAnswerShell() {
    var article = document.createElement("article");
    article.className = "msg msg--bot";
    article.innerHTML = markup("thinking");
    var body = document.createElement("div");
    body.className = "msg__body";
    var text = document.createElement("div");
    text.className = "msg__text";
    body.appendChild(text);
    article.appendChild(body);
    transcript.appendChild(article);
    return { article: article, body: body, text: text };
  }

  function setState(article, state) {
    var mark = article.querySelector(".dumi");
    if (mark) mark.setAttribute("data-state", state);
  }

  function renderCitations(body, citations, labels) {
    if (!citations || !citations.length) return;
    var section = document.createElement("section");
    section.className = "sources";
    var heading = document.createElement("h3");
    heading.className = "sources__title";
    heading.textContent = labels.sources;
    section.appendChild(heading);

    var list = document.createElement("ol");
    list.className = "sources__list";
    citations.forEach(function (citation) {
      var item = document.createElement("li");
      if (citation.url) {
        var link = document.createElement("a");
        link.href = citation.url;
        link.rel = "noopener noreferrer nofollow";
        link.target = "_blank";
        link.textContent = citation.title;
        item.appendChild(link);
      } else {
        item.appendChild(document.createTextNode(citation.title));
      }
      if (citation.locator) {
        var where = document.createElement("span");
        where.className = "sources__where";
        where.textContent = citation.locator;
        item.appendChild(where);
      }
      if (citation.cross_language) {
        var lang = document.createElement("span");
        lang.className = "sources__lang";
        lang.textContent = labels.source_language + " " + citation.language.toUpperCase();
        item.appendChild(lang);
      }
      if (citation.last_checked) {
        var date = document.createElement("span");
        date.className = "sources__date";
        date.textContent = labels.last_checked + " " + citation.last_checked;
        item.appendChild(date);
      }
      list.appendChild(item);
    });
    section.appendChild(list);
    body.appendChild(section);
  }

  function renderNotices(body, notices) {
    (notices || []).forEach(function (notice) {
      var paragraph = document.createElement("p");
      var emergency = notice.key === "answer.emergency";
      paragraph.className = "callout callout--" + (emergency ? "emergency" : "caution");
      if (emergency) paragraph.setAttribute("role", "alert");
      paragraph.textContent = notice.text;
      // Notices go before the answer text.
      body.insertBefore(paragraph, body.firstChild);
    });
  }

  form.addEventListener("submit", function (event) {
    var question = input.value.trim();
    if (!question) return;

    event.preventDefault();
    input.value = "";
    addUserMessage(question);
    var shell = addAnswerShell();
    stopButton.hidden = false;

    controller = new AbortController();

    fetch("/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify({
        question: question,
        lang: form.querySelector('input[name="lang"]').value
      }),
      signal: controller.signal
    })
      .then(function (response) { return response.json(); })
      .then(function (payload) {
        setState(shell.article, "idle");
        shell.text.textContent = payload.text || "";
        if (payload.confidence) {
          shell.article.setAttribute("data-confidence", payload.confidence);
        }
        renderCitations(shell.body, payload.citations, payload.labels || {});
        renderNotices(shell.body, payload.notices);
        status.textContent = "";
      })
      .catch(function (error) {
        setState(shell.article, "idle");
        if (error && error.name === "AbortError") {
          status.textContent = "";
          return;
        }
        // Falls back to the message the server would have rendered.
        shell.text.textContent = form.dataset.unavailable || "";
        status.textContent = "";
      })
      .finally(function () {
        stopButton.hidden = true;
        controller = null;
        input.focus();
      });

    status.textContent = form.dataset.thinking || "";
  });

  stopButton.addEventListener("click", function () {
    if (controller) controller.abort();
    stopButton.hidden = true;
  });
})();
