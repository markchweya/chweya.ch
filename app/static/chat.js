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

  // The welcome state exists only while the transcript is empty. The first
  // message removes it and restores the ordinary chat layout.
  var hero = document.getElementById("hero");
  var suggestions = document.getElementById("suggestions");

  function leaveWelcome() {
    if (hero) { hero.remove(); hero = null; }
    if (suggestions) { suggestions.remove(); suggestions = null; }
    var main = document.getElementById("main");
    if (main) main.classList.remove("chat--welcome");
  }

  // The language menu is a native disclosure and works without any script;
  // this only closes it when the person clicks somewhere else, which the
  // element does not do on its own.
  document.addEventListener("click", function (event) {
    var open = document.querySelector(".lang-menu[open]");
    if (open && !open.contains(event.target)) open.removeAttribute("open");
  });

  if (suggestions) {
    suggestions.addEventListener("click", function (event) {
      var button = event.target.closest("button.suggestion");
      if (!button) return;
      // Without this the button also submits the form natively; with it the
      // question goes through the same streamed path as a typed one.
      event.preventDefault();
      input.value = button.value;
      form.requestSubmit();
    });
  }

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

    // The waiting sentence, in the user's language, beside the mark. Static
    // text: the mark's own motion is the status indicator, this only says
    // in words what the motion means. aria-hidden because the same sentence
    // is announced through the status region; the transcript is a live
    // region and would otherwise announce it twice.
    var thinking = null;
    if (form.dataset.thinking) {
      thinking = document.createElement("span");
      thinking.className = "msg__thinking";
      thinking.setAttribute("aria-hidden", "true");
      thinking.textContent = form.dataset.thinking;
      article.appendChild(thinking);
    }

    transcript.appendChild(article);
    var shell = {
      article: article,
      body: null,
      text: null,
      // The waiting sentence leaves the moment anything real happens: the
      // first words, the final answer, an error, or a stop.
      settle: function () {
        if (thinking) {
          thinking.remove();
          thinking = null;
        }
      },
      // The body is created only when there is something to put in it. An
      // empty bubble reads as a broken message.
      ensureBody: function () {
        shell.settle();
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

  // The final answer is plain text with one recognised structure:
  // consecutive lines whose cells are separated by " | " become a real
  // table, because holiday dates and fee schedules arrive from the canton's
  // pages as rows and a wall of pipe characters is unreadable. Every cell
  // is written with textContent; nothing the model wrote is rendered as
  // HTML.
  function isTableRow(line) {
    return line.indexOf(" | ") !== -1;
  }

  function buildTable(rows) {
    var wrap = document.createElement("div");
    wrap.className = "answer-table";
    var table = document.createElement("table");
    rows.forEach(function (row) {
      var tr = document.createElement("tr");
      row.split(" | ").forEach(function (cell) {
        var td = document.createElement("td");
        td.textContent = cell.trim();
        tr.appendChild(td);
      });
      table.appendChild(tr);
    });
    wrap.appendChild(table);
    return wrap;
  }

  // Lines starting "1." or "1)" are steps and become a real ordered list.
  var STEP_LINE = /^\d{1,2}[.)]\s+/;

  // The final answer is rendered as blocks, mirroring the server template:
  // blank lines separate paragraphs, "- " lines become a list, numbered
  // lines become steps, and " | " rows become a table. This is what makes a
  // long answer readable on a phone instead of a wall of text.
  function renderAnswerText(target, text) {
    target.textContent = "";
    target.classList.add("msg__text--blocks");
    var lines = text.split("\n");
    var i = 0;

    function isBullet(line) {
      return line.trim().indexOf("- ") === 0;
    }

    while (i < lines.length) {
      var stripped = lines[i].trim();
      if (isTableRow(lines[i])) {
        var rows = [];
        while (i < lines.length && isTableRow(lines[i])) {
          rows.push(lines[i]);
          i += 1;
        }
        target.appendChild(buildTable(rows));
      } else if (isBullet(lines[i])) {
        var list = document.createElement("ul");
        while (i < lines.length && isBullet(lines[i])) {
          var item = document.createElement("li");
          item.textContent = lines[i].trim().slice(2).trim();
          list.appendChild(item);
          i += 1;
        }
        target.appendChild(list);
      } else if (STEP_LINE.test(stripped)) {
        var steps = document.createElement("ol");
        var first = parseInt(stripped, 10);
        if (first > 1) {
          steps.setAttribute("start", String(first));
        }
        while (i < lines.length && STEP_LINE.test(lines[i].trim())) {
          var step = document.createElement("li");
          step.textContent = lines[i].trim().replace(STEP_LINE, "");
          steps.appendChild(step);
          i += 1;
        }
        target.appendChild(steps);
      } else if (stripped) {
        var prose = [];
        while (i < lines.length) {
          var line = lines[i].trim();
          if (!line || isTableRow(lines[i]) || isBullet(lines[i]) || STEP_LINE.test(line)) {
            break;
          }
          prose.push(line);
          i += 1;
        }
        var paragraph = document.createElement("p");
        paragraph.textContent = prose.join(" ");
        target.appendChild(paragraph);
      } else {
        i += 1;
      }
    }
  }

  // One transient confirmation, reused by every toast. role="status" so the
  // thanks is announced as well as shown. No animation: it appears, waits,
  // and leaves.
  function showToast(text) {
    var toast = document.getElementById("toast");
    if (!toast) {
      toast = document.createElement("div");
      toast.id = "toast";
      toast.className = "toast";
      toast.setAttribute("role", "status");
      document.body.appendChild(toast);
    }
    toast.textContent = text;
    toast.hidden = false;
    clearTimeout(showToast.timer);
    showToast.timer = setTimeout(function () { toast.hidden = true; }, 2500);
  }

  function renderFeedback(body, payload) {
    var labels = payload.labels || {};
    if (!labels.feedback_up) return;
    var row = document.createElement("div");
    row.className = "feedback";

    function thumbButton(vote, label, path) {
      var button = document.createElement("button");
      button.type = "button";
      button.className = "feedback__button";
      button.title = label;
      button.setAttribute("aria-pressed", "false");
      var name = document.createElement("span");
      name.className = "visually-hidden";
      name.textContent = label;
      button.appendChild(name);
      button.insertAdjacentHTML(
        "beforeend",
        '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor"' +
        ' stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
        path + "</svg>"
      );
      button.addEventListener("click", function () {
        // One vote per answer. The buttons lock before the request, so a
        // double click cannot record twice.
        row.querySelectorAll("button").forEach(function (b) { b.disabled = true; });
        button.setAttribute("aria-pressed", "true");
        fetch("/feedback", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            vote: vote,
            language: payload.language,
            confidence: payload.confidence,
            is_refusal: payload.is_refusal,
            citations: (payload.citations || [])
              .map(function (c) { return c.url; })
              .filter(Boolean)
          })
        }).catch(function () {});
        showToast(labels.feedback_thanks || "");
      });
      return button;
    }

    row.appendChild(thumbButton("up", labels.feedback_up,
      '<path d="M7 10v12"/><path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z"/>'));
    row.appendChild(thumbButton("down", labels.feedback_down,
      '<path d="M17 14V2"/><path d="M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22a3.13 3.13 0 0 1-3-3.88Z"/>'));
    body.appendChild(row);
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
    leaveWelcome();
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
      renderAnswerText(shell.text, payload.text || "");
      if (payload.confidence) {
        shell.article.setAttribute("data-confidence", payload.confidence);
      }
      renderCitations(shell.body, payload.citations, payload.labels || {});
      renderNotices(shell.body, payload.notices);
      renderFeedback(shell.body, payload);
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
        shell.settle();
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
