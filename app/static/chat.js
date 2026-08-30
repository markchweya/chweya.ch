/* Progressive enhancement for the chat form.
 *
 * The form works without JavaScript: it posts and the server renders the full
 * page. This file upgrades that to a streamed answer, and falls back silently
 * if anything is unavailable.
 *
 * What it must get right for accessibility:
 *  - The transcript is a live region, so appended text is announced. Streamed
 *    tokens are buffered to sentence boundaries before being written, because
 *    announcing every token makes a screen reader unusable.
 *  - There is a stop control while a response is streaming.
 *  - The Dumi mark carries status. No spinner is created anywhere, and no
 *    answer card exists until there is answer text to put in it: an empty
 *    bubble reads as a broken message, the mark alone reads as thinking.
 */
(function () {
  "use strict";

  var form = document.getElementById("ask");
  var input = document.getElementById("question");
  var transcript = document.getElementById("transcript");
  var status = document.getElementById("status");
  var stopButton = document.getElementById("stop");
  var sendButton = document.getElementById("send");
  if (!form || !input || !transcript) return;

  var controller = null;

  // The same Markdown-marker removal the server applies to the final text,
  // so the provisional streamed text does not show literal asterisks for the
  // minutes a slow model takes. Only markers are removed, never words, and
  // the text is still written with textContent: this is not rendering
  // Markdown, it is refusing to display its punctuation.
  function plain(text) {
    return text
      .replace(/^#{1,6}[ \t]+/gm, "")
      .replace(/\*\*([^*]+)\*\*/g, "$1")
      .replace(/__([^_]+)__/g, "$1")
      .replace(/^[ \t]*\*[ \t]+/gm, "- ")
      .replace(/`+/g, "")
      .replace(/\*\*/g, "");
  }

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
    transcript.appendChild(article);
    var shell = {
      article: article,
      body: null,
      text: null,
      // The card is created only when there is something to put in it. Until
      // then the mark alone carries the waiting state; it is the product's
      // one status indicator.
      ensureBody: function () {
        if (!shell.body) {
          shell.body = document.createElement("div");
          shell.body.className = "msg__body";
          shell.text = document.createElement("div");
          shell.text.className = "msg__text";
          shell.body.appendChild(shell.text);
          article.appendChild(shell.body);
        }
        return shell.body;
      }
    };
    return shell;
  }

  function setState(article, state) {
    var mark = article.querySelector(".dumi");
    if (mark) mark.setAttribute("data-state", state);
  }

  function renderCitations(body, citations, labels) {
    if (!citations || !citations.length) return;
    // The same collapsed disclosure the server renders. The two paths must
    // produce the same page, or the no-script experience quietly diverges.
    var section = document.createElement("details");
    section.className = "sources";
    var summary = document.createElement("summary");
    summary.className = "sources__summary";
    summary.innerHTML =
      '<svg class="sources__chevron" viewBox="0 0 24 24" width="14" height="14"' +
      ' fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"' +
      ' stroke-linejoin="round" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg>';
    summary.appendChild(
      document.createTextNode(labels.sources + " (" + citations.length + ")")
    );
    section.appendChild(summary);

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
    if (sendButton) sendButton.hidden = true;

    controller = new AbortController();

    // What the stream has shown so far, and what is buffered awaiting a
    // sentence boundary. The final payload's text replaces all of it:
    // citation validation happens server-side only at the end, so the
    // accumulated text is provisional by design.
    var shown = "";
    var pending = "";

    function flushSentences(force) {
      if (force) {
        shown += pending;
        pending = "";
      } else {
        // Greedy to the LAST sentence boundary, so one flush can carry
        // several sentences and the live region announces prose, not tokens.
        var match = pending.match(/^[\s\S]*[.!?:\n](?=\s|$)/);
        if (!match) return;
        shown += match[0];
        pending = pending.slice(match[0].length);
      }
      if (shown) {
        shell.ensureBody();
        shell.text.textContent = plain(shown);
      }
    }

    function finish(payload) {
      setState(shell.article, "idle");
      shell.ensureBody();
      // Authoritative: invented citation markers are stripped server-side
      // only in this text, so it replaces whatever was streamed.
      shell.text.textContent = payload.text || "";
      if (payload.confidence) {
        shell.article.setAttribute("data-confidence", payload.confidence);
      }
      renderCitations(shell.body, payload.citations, payload.labels || {});
      renderNotices(shell.body, payload.notices);
      status.textContent = "";
    }

    function handleEvent(data) {
      var event;
      try {
        event = JSON.parse(data);
      } catch (error) {
        return;
      }
      if (event.type === "delta") {
        pending += event.text;
        flushSentences(false);
      } else if (event.type === "final") {
        finish(event.payload);
      }
    }

    function readStream(response) {
      var reader = response.body.getReader();
      var decoder = new TextDecoder();
      var carry = "";
      function pump() {
        return reader.read().then(function (step) {
          if (step.done) return;
          carry += decoder.decode(step.value, { stream: true });
          var frames = carry.split("\n\n");
          carry = frames.pop();
          frames.forEach(function (frame) {
            frame.split("\n").forEach(function (line) {
              if (line.indexOf("data:") === 0) {
                handleEvent(line.slice(5).replace(/^\s/, ""));
              }
            });
          });
          return pump();
        });
      }
      return pump();
    }

    fetch("/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "text/event-stream" },
      body: JSON.stringify({
        question: question,
        lang: form.querySelector('input[name="lang"]').value
      }),
      signal: controller.signal
    })
      .then(function (response) {
        var type = response.headers.get("Content-Type") || "";
        if (type.indexOf("text/event-stream") === -1) {
          // Not a stream: rate limiting and errors answer in JSON, and so
          // would a deployment with streaming turned off at a proxy.
          return response.json().then(finish);
        }
        return readStream(response);
      })
      .catch(function (error) {
        setState(shell.article, "idle");
        if (error && error.name === "AbortError") {
          // The person stopped the answer. What has been shown stays; the
          // buffer is flushed so the last words are not lost mid-sentence.
          flushSentences(true);
          status.textContent = "";
          return;
        }
        // A failed or interrupted stream must not stand as a finished
        // answer. The fixed unavailable message replaces the partial text.
        shell.ensureBody();
        shell.text.textContent = form.dataset.unavailable || "";
        status.textContent = "";
      })
      .finally(function () {
        stopButton.hidden = true;
        if (sendButton) sendButton.hidden = false;
        controller = null;
        input.focus();
      });

    status.textContent = form.dataset.thinking || "";
  });

  stopButton.addEventListener("click", function () {
    if (controller) controller.abort();
    stopButton.hidden = true;
    if (sendButton) sendButton.hidden = false;
  });
})();
