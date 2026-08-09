const domains = {
  vocabulary: "Vocabulary",
  math: "Math",
  english: "Reading & Writing",
};

const fallbackTaxonomy = {
  topics: {
    vocabulary: [],
    math: [
      "Algebra",
      "Advanced Math",
      "Problem-Solving and Data Analysis",
      "Geometry and Trigonometry",
    ],
    english: [
      "Information and Ideas",
      "Craft and Structure",
      "Expression of Ideas",
      "Standard English Conventions",
    ],
  },
  difficulties: ["Easy", "Medium", "Hard"],
};

const state = {
  stats: null,
  sources: [],
  activeSessions: [],
  completedSessions: [],
  taxonomy: fallbackTaxonomy,
  session: null,
  index: 0,
  score: 0,
  flashFlipped: false,
  flashPass: 1,
  flashHistory: [],
  flashAdvancing: false,
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || "Request failed.");
  }
  return payload;
}

function toast(message) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.add("visible");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => node.classList.remove("visible"), 3200);
}

function showView(viewName) {
  $$(".view").forEach((view) => view.classList.toggle("active", view.id === viewName));
  $$(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.view === viewName));
}

function sourceOptions(domain, includeEmpty = true) {
  const rows = state.sources.filter((source) => source.domain === domain);
  const empty = includeEmpty ? `<option value="">No source</option>` : "";
  return `${empty}${rows
    .map((source) => `<option value="${source.id}">${escapeHtml(source.title)}</option>`)
    .join("")}`;
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function topicsFor(domain) {
  return state.taxonomy?.topics?.[domain] || [];
}

function difficulties() {
  return state.taxonomy?.difficulties || fallbackTaxonomy.difficulties;
}

function optionList(values, selected = "") {
  return values
    .map(
      (value) =>
        `<option value="${escapeHtml(value)}" ${value === selected ? "selected" : ""}>${escapeHtml(
          value
        )}</option>`
    )
    .join("");
}

function checkboxGroup(name, values, selectedValues = values) {
  const selected = new Set(selectedValues);
  return values
    .map(
      (value) => `
        <label class="check-pill">
          <input type="checkbox" name="${name}" value="${escapeHtml(value)}" ${
        selected.has(value) ? "checked" : ""
      }>
          <span>${escapeHtml(value)}</span>
        </label>
      `
    )
    .join("");
}

function selectedCheckboxValues(root, name) {
  return $$(`input[name="${name}"]:checked`, root).map((input) => input.value);
}

function shuffleInPlace(items) {
  for (let index = items.length - 1; index > 0; index -= 1) {
    const swapIndex = Math.floor(Math.random() * (index + 1));
    [items[index], items[swapIndex]] = [items[swapIndex], items[index]];
  }
  return items;
}

function sessionSize(mode) {
  return Number(mode === "review" ? $("#review-size")?.value || 10 : 10);
}

function cardTestSize(domain) {
  const card = $(`[data-domain-card="${domain}"]`);
  return Number($("[data-test-size]", card)?.value || 10);
}

function orientFlashcard(item, direction) {
  const actualDirection =
    direction === "mixed"
      ? Math.random() > 0.5
        ? "word_to_definition"
        : "definition_to_word"
      : direction;
  if (actualDirection === "definition_to_word") {
    item.front = item.answer;
    item.back = item.prompt;
    item.front_label = "Definition";
    item.back_label = "Word";
  } else {
    item.front = item.prompt;
    item.back = item.answer;
    item.front_label = "Word";
    item.back_label = "Definition";
  }
  item.direction = actualDirection;
  return item;
}

function prepareFlashDeck() {
  const direction = state.session?.direction || "mixed";
  state.session.items.forEach((item) => orientFlashcard(item, direction));
  shuffleInPlace(state.session.items);
}

function getDashboardFilters(domain) {
  const card = $(`[data-domain-card="${domain}"]`);
  if (!card || domain === "vocabulary") {
    return { topics: [], difficulties: [] };
  }
  const topicValues = topicsFor(domain);
  const difficultyValues = difficulties();
  const topics = selectedCheckboxValues(card, "topics");
  const selectedDifficulties = selectedCheckboxValues(card, "difficulties");
  if (!topics.length) {
    throw new Error("Choose at least one topic.");
  }
  if (!selectedDifficulties.length) {
    throw new Error("Choose at least one difficulty.");
  }
  return {
    topics: topics.length === topicValues.length ? [] : topics,
    difficulties:
      selectedDifficulties.length === difficultyValues.length ? [] : selectedDifficulties,
  };
}

function filterSummary(domain, filters = {}) {
  if (domain === "vocabulary") return "";
  const topics = filters.topics?.length ? filters.topics.join(", ") : "All topics";
  const diffs = filters.difficulties?.length
    ? filters.difficulties.join(", ")
    : "All difficulties";
  return `${topics} / ${diffs}`;
}

function questionMeta(item) {
  const parts = [
    item.question_identifier ? `ID ${item.question_identifier}` : "",
    item.topic,
    item.subtopic,
    item.difficulty,
  ].filter(Boolean);
  return parts.length ? `<div class="meta-chips">${parts.map((part) => `<span>${escapeHtml(part)}</span>`).join("")}</div>` : "";
}

function mediaUrl(value) {
  const src = String(value || "").trim();
  if (!src) return "";
  if (/^(https?:|data:)/i.test(src) || src.startsWith("/api/") || src.startsWith("/static/")) {
    return src;
  }
  return `/api/media?path=${encodeURIComponent(src)}`;
}

function promptImagesHtml(item) {
  const images = item.media?.prompt_images || [];
  if (!images.length) return "";
  return `
    <div class="media-grid">
      ${images
        .map((image) => `<img src="${escapeHtml(mediaUrl(image))}" alt="Question image">`)
        .join("")}
    </div>
  `;
}

function choiceImageHtml(item, index) {
  const image = item.media?.choice_images?.[index];
  if (!image) return "";
  return `<img class="choice-image" src="${escapeHtml(mediaUrl(image))}" alt="">`;
}

function firstUnansweredIndex(session) {
  const index = session.items.findIndex((item) => !item.answered);
  return index === -1 ? session.items.length : index;
}

function freshCount(stats = {}) {
  return `${stats.unseen || 0}/${stats.total || 0}`;
}

function formatDateTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString([], {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function renderActiveSessions() {
  const target = $("#active-session-list");
  if (!state.activeSessions.length) {
    target.innerHTML = "";
    return;
  }
  target.innerHTML = `
    <div class="resume-panel">
      <div>
        <h3>Continue Practice</h3>
        <p>Resume unfinished tests from the last saved answer.</p>
      </div>
      <div class="resume-list">
        ${state.activeSessions
          .map(
            (session) => `
              <button class="resume-row" data-resume-session="${session.session_id}">
                <span>${domains[session.domain]} ${session.mode === "review" ? "Review" : "Test"}</span>
                <small>${session.answered_count} of ${session.count} answered</small>
              </button>
            `
          )
          .join("")}
      </div>
    </div>
  `;
  $$("[data-resume-session]", target).forEach((button) => {
    button.addEventListener("click", () => resumeSession(button.dataset.resumeSession));
  });
}

function renderTestHistory() {
  const panel = $("#history-panel");
  if (!panel) return;
  if (!state.completedSessions.length) {
    panel.innerHTML = `
      <div class="empty-state">
        <div>
          <h3>No completed tests yet</h3>
          <p>Completed tests will appear here with all questions and explanations.</p>
        </div>
      </div>
    `;
    return;
  }
  panel.innerHTML = `
    <div class="history-list">
      ${state.completedSessions
        .map((session) => {
          const label = `${domains[session.domain]} ${
            session.mode === "review" ? "Review" : "Test"
          }`;
          const filterText = filterSummary(session.domain, session.filters);
          return `
            <button class="history-row" data-history-session="${session.session_id}">
              <span>
                <b>${label}</b>
                <small>${formatDateTime(session.completed_at)}</small>
              </span>
              <span>
                <b>${session.score}/${session.count}</b>
                <small>${session.wrong_count || 0} missed${filterText ? ` / ${filterText}` : ""}</small>
              </span>
            </button>
          `;
        })
        .join("")}
    </div>
  `;
  $$("[data-history-session]", panel).forEach((button) => {
    button.addEventListener("click", () => viewHistorySession(button.dataset.historySession));
  });
}

function renderDashboard() {
  renderActiveSessions();
  const grid = $("#domain-grid");
  grid.innerHTML = Object.entries(domains)
    .map(([domain, label]) => {
      const stats = state.stats?.domains?.[domain] || {};
      const topicValues = topicsFor(domain);
      const filters =
        topicValues.length > 0
          ? `
            <div class="filter-block">
              <div class="filter-title">Topics</div>
              <div class="check-grid">${checkboxGroup("topics", topicValues)}</div>
            </div>
            <div class="filter-block">
              <div class="filter-title">Difficulty</div>
              <div class="check-grid compact">${checkboxGroup("difficulties", difficulties())}</div>
            </div>
          `
          : "";
      return `
        <article class="domain-card" data-domain-card="${domain}">
          <header>
            <div>
              <h3>${label}</h3>
              <p>${domain === "english" ? "Reading, comprehension, grammar" : "Practice area"}</p>
            </div>
            <span class="badge">${stats.total || 0}</span>
          </header>
          <div class="metric-grid">
            <div class="metric"><b>${freshCount(stats)}</b><span>Fresh</span></div>
            <div class="metric"><b>${stats.due || 0}</b><span>Due</span></div>
            <div class="metric"><b>${stats.review || 0}</b><span>Review</span></div>
            <div class="metric"><b>${stats.sources || 0}</b><span>Sources</span></div>
          </div>
          ${filters}
          <label class="card-control">
            Test Size
            <select data-test-size>
              <option value="10">10 questions</option>
              <option value="20">20 questions</option>
              <option value="30">30 questions</option>
            </select>
          </label>
          <div class="actions">
            <button data-start-test="${domain}">Start Test</button>
            <button class="secondary" data-review="${domain}">Review</button>
          </div>
        </article>
      `;
    })
    .join("");

  $$("[data-start-test]").forEach((button) => {
    button.addEventListener("click", () => {
      try {
        startSession(
          button.dataset.startTest,
          "test",
          "#test-panel",
          getDashboardFilters(button.dataset.startTest),
          cardTestSize(button.dataset.startTest)
        );
      } catch (error) {
        toast(error.message);
      }
    });
  });
  $$("[data-review]").forEach((button) => {
    button.addEventListener("click", () => {
      $("#review-domain").value = button.dataset.review;
      showView("review");
      startSession(button.dataset.review, "review", "#review-panel");
    });
  });
}

function renderSettings() {
  const panel = $("#settings-panel");
  if (!panel) return;
  panel.innerHTML = Object.entries(domains)
    .map(([domain, label]) => {
      const stats = state.stats?.domains?.[domain] || {};
      const activeCount = state.activeSessions.filter((session) => session.domain === domain).length;
      return `
        <article class="settings-card" data-settings-domain="${domain}">
          <header>
            <div>
              <h3>${label}</h3>
              <p>Question bank and sources stay in place.</p>
            </div>
            <span class="badge">${stats.total || 0}</span>
          </header>
          <div class="metric-grid">
            <div class="metric"><b>${freshCount(stats)}</b><span>Fresh</span></div>
            <div class="metric"><b>${stats.due || 0}</b><span>Due</span></div>
            <div class="metric"><b>${stats.review || 0}</b><span>Review</span></div>
            <div class="metric"><b>${stats.seen_attempts || 0}</b><span>Seen</span></div>
            <div class="metric"><b>${stats.correct_answers || 0}</b><span>Correct</span></div>
            <div class="metric"><b>${stats.wrong_answers || 0}</b><span>Wrong</span></div>
          </div>
          <p class="settings-note">
            Clears attempts, in-progress sessions (${activeCount}), review flags, mastery, due dates, and correct/wrong counters. Completed test history is kept.
          </p>
          <div class="actions">
            <button class="danger" data-reset-progress="${domain}">Reset ${label}</button>
          </div>
        </article>
      `;
    })
    .join("");

  $$("[data-reset-progress]", panel).forEach((button) => {
    button.addEventListener("click", () => resetDomainProgress(button.dataset.resetProgress));
  });
}

async function resetDomainProgress(domain) {
  const label = domains[domain] || domain;
  const confirmed = confirm(
    `Reset ${label} progress? This keeps questions, sources, and completed test history, but clears attempts, in-progress sessions, review flags, due dates, and correct/wrong counters.`
  );
  if (!confirmed) return;
  const result = await api("/api/progress/reset", {
    method: "POST",
    body: JSON.stringify({ domain }),
  });
  if (state.session?.domain === domain) {
    state.session = null;
  }
  toast(`Reset ${label} progress for ${result.items_reset} item${result.items_reset === 1 ? "" : "s"}.`);
  await loadAll();
}

function renderSources() {
  $("#item-source").innerHTML = sourceOptions($("#item-domain").value);
  $("#import-source").innerHTML = sourceOptions($("#import-domain").value);
  const sourceList = $("#source-list");
  if (!state.sources.length) {
    sourceList.innerHTML = `<div class="empty-state">No sources yet.</div>`;
    return;
  }
  sourceList.innerHTML = state.sources
    .map(
      (source) => `
        <div class="source-row">
          <strong>${escapeHtml(source.title)}</strong>
          <small>${domains[source.domain]} / ${escapeHtml(source.kind)} / ${source.item_count} items / ${source.page_count || 0} pages</small>
          <small>${escapeHtml(source.locator || source.notes || "")}</small>
          ${
            source.kind === "pdf"
              ? `<button class="secondary compact-button" data-extract-source="${source.id}">Extract PDF</button>`
              : ""
          }
        </div>
      `
    )
    .join("");
  $$("[data-extract-source]", sourceList).forEach((button) => {
    button.addEventListener("click", async () => {
      button.disabled = true;
      button.textContent = "Extracting...";
      try {
        const result = await api("/api/sources/extract", {
          method: "POST",
          body: JSON.stringify({ source_id: button.dataset.extractSource }),
        });
        toast(`Extracted ${result.pages} PDF page${result.pages === 1 ? "" : "s"}.`);
        await loadAll();
      } finally {
        button.disabled = false;
        button.textContent = "Extract PDF";
      }
    });
  });
}

function syncItemFormForDomain() {
  const domain = $("#item-domain").value;
  $("#item-source").innerHTML = sourceOptions(domain);
  const hasTopics = topicsFor(domain).length > 0;
  $("#item-topic").innerHTML = optionList(topicsFor(domain));
  $("#item-topic").disabled = !hasTopics;
  $("#item-subtopic").disabled = !hasTopics;
  $("#item-difficulty").disabled = !hasTopics;
  $("#item-topic-label").style.display = hasTopics ? "grid" : "none";
  $("#item-subtopic-label").style.display = hasTopics ? "grid" : "none";
  $("#item-difficulty-label").style.display = hasTopics ? "grid" : "none";
  $("#question-identifier").disabled = domain === "vocabulary";
  $("#question-identifier-label").style.display = domain === "vocabulary" ? "none" : "grid";
  $("#choices-label").style.display = domain === "vocabulary" ? "none" : "grid";
  $("#prompt-images-label").style.display = domain === "vocabulary" ? "none" : "grid";
  $("#choice-images-label").style.display = domain === "vocabulary" ? "none" : "grid";
  $("#prompt-label").firstChild.textContent = domain === "vocabulary" ? "Word" : "Question";
  $("#answer-label").firstChild.textContent =
    domain === "vocabulary" ? "Definition" : "Correct answer";
}

function syncImportFormForDomain() {
  const domain = $("#import-domain").value;
  $("#import-source").innerHTML = sourceOptions(domain);
  const hasTopics = topicsFor(domain).length > 0;
  $("#import-topic").innerHTML = optionList(topicsFor(domain));
  $("#import-topic").disabled = !hasTopics;
  $("#import-subtopic").disabled = !hasTopics;
  $("#import-difficulty").disabled = !hasTopics;
  $("#import-topic-label").style.display = hasTopics ? "grid" : "none";
  $("#import-subtopic-label").style.display = hasTopics ? "grid" : "none";
  $("#import-difficulty-label").style.display = hasTopics ? "grid" : "none";
  $("#import-mode").value = domain === "vocabulary" ? "vocabulary" : "questions_tsv";
}

async function loadAll() {
  const [stats, sources, taxonomy, sessions, completedSessions] = await Promise.all([
    api("/api/stats"),
    api("/api/sources"),
    api("/api/taxonomy"),
    api("/api/sessions/active"),
    api("/api/sessions/completed"),
  ]);
  state.stats = stats;
  state.sources = sources.sources;
  state.taxonomy = taxonomy;
  state.activeSessions = sessions.sessions;
  state.completedSessions = completedSessions.sessions;
  renderDashboard();
  renderTestHistory();
  renderSettings();
  renderSources();
  syncItemFormForDomain();
  syncImportFormForDomain();
}

async function startSession(
  domain,
  mode,
  panelSelector = "#test-panel",
  filters = null,
  countOverride = null
) {
  const count = countOverride || sessionSize(mode);
  const direction = mode === "flashcards" ? $("#flash-direction").value : "mixed";
  const selectedFilters = filters || { topics: [], difficulties: [] };
  const session = await api("/api/session", {
    method: "POST",
    body: JSON.stringify({ domain, mode, count, direction, ...selectedFilters }),
  });
  state.session = session;
  state.session.filters = selectedFilters;
  state.session.direction = direction;
  state.session.requestedCount = count;
  state.index = firstUnansweredIndex(session);
  state.score = 0;
  state.flashFlipped = false;
  state.flashPass = 1;
  state.flashHistory = [];
  state.flashAdvancing = false;

  if (mode === "test") {
    $("#test-title").textContent = `${domains[domain]} Test`;
    $("#test-subtitle").textContent = `${session.count} item${
      session.count === 1 ? "" : "s"
    } ready${filterSummary(domain, selectedFilters) ? ` / ${filterSummary(domain, selectedFilters)}` : ""}`;
    showView("test");
    renderQuestion(panelSelector);
  } else if (mode === "review") {
    showView("review");
    renderQuestion(panelSelector);
  } else {
    prepareFlashDeck();
    showView("flashcards");
    renderFlashcard();
  }
}

async function resumeSession(sessionId) {
  const session = await api(`/api/session?session_id=${encodeURIComponent(sessionId)}`);
  state.session = session;
  state.session.filters = session.filters || { topics: [], difficulties: [] };
  state.session.requestedCount = session.requested_count || session.count || 10;
  state.index = firstUnansweredIndex(session);
  state.score = 0;
  if (session.mode === "review") {
    showView("review");
    renderQuestion("#review-panel");
  } else {
    $("#test-title").textContent = `${domains[session.domain]} Test`;
    $("#test-subtitle").textContent = `${session.count} item${
      session.count === 1 ? "" : "s"
    } ready${filterSummary(session.domain, session.filters) ? ` / ${filterSummary(session.domain, session.filters)}` : ""}`;
    showView("test");
    renderQuestion("#test-panel");
  }
}

async function viewHistorySession(sessionId) {
  const session = await api(`/api/session?session_id=${encodeURIComponent(sessionId)}`);
  state.session = session;
  state.index = 0;
  showView("history");
  renderResults("#history-panel");
}

function currentItem() {
  return state.session?.items?.[state.index];
}

function hasSelectedAnswer(item) {
  return Boolean(String(item?.selected_answer || "").trim());
}

async function completeCurrentSession(panelSelector) {
  const panel = $(panelSelector);
  if (!state.session?.session_id) {
    return;
  }
  panel.innerHTML = `<div class="empty-state">Scoring test...</div>`;
  const session = await api("/api/session/complete", {
    method: "POST",
    body: JSON.stringify({ session_id: state.session.session_id }),
  });
  state.session = session;
  renderResults(panelSelector);
  await loadAll();
}

function selectedAnswerHtml(item) {
  if (!item.selected_answer) return "";
  const inChoices = (item.choices || []).some(
    (choice) => normalize(choice) === normalize(item.selected_answer)
  );
  if (inChoices) return "";
  return `
    <div class="typed-answer ${item.correct ? "correct" : "incorrect"}">
      Selected: ${escapeHtml(item.selected_answer)}
    </div>
  `;
}

function choiceDisplayText(choice, index) {
  const value = String(choice || "").trim();
  if (/^[A-D]$/.test(value)) return value;
  return `${String.fromCharCode(65 + index)}. ${value}`;
}

function resultChoicesHtml(item) {
  const choices = item.choices || [];
  if (!choices.length) return selectedAnswerHtml(item);
  return `
    <div class="choices result-choices">
      ${choices
        .map((choice, index) => {
          const selected = normalize(choice) === normalize(item.selected_answer);
          const correct = normalize(choice) === normalize(item.answer);
          const classes = [
            "choice",
            "static-choice",
            correct ? "correct" : "",
            selected && !item.correct ? "incorrect" : "",
            selected ? "selected" : "",
          ]
            .filter(Boolean)
            .join(" ");
          return `
            <div class="${classes}">
              <span>${escapeHtml(choiceDisplayText(choice, index))}</span>
              ${choiceImageHtml(item, index)}
            </div>
          `;
        })
        .join("")}
    </div>
    ${selectedAnswerHtml(item)}
  `;
}

function renderResults(panelSelector) {
  const panel = $(panelSelector);
  const session = state.session;
  const wrongCount = session.items.filter((item) => !item.correct).length;
  const isHistory = panelSelector === "#history-panel";
  panel.innerHTML = `
    <div class="results-shell">
      <div class="results-summary">
        <div>
          <h3>${session.mode === "review" ? "Review Complete" : "Test Complete"}</h3>
          <p>Score: ${session.score} of ${session.count} / ${wrongCount} missed</p>
        </div>
        <button id="results-back">${isHistory ? "Back to History" : "Dashboard"}</button>
      </div>
      <div class="results-list">
        ${session.items
          .map(
            (item, index) => `
              <article class="result-card">
                <div class="progress-line">
                  <span>Question ${index + 1}</span>
                  <span class="${item.correct ? "result-ok" : "result-miss"}">${
              item.correct ? "Correct" : "Incorrect"
            }</span>
                </div>
                ${questionMeta(item)}
                <div class="prompt">${escapeHtml(item.question_prompt || item.prompt)}</div>
                ${promptImagesHtml(item)}
                ${resultChoicesHtml(item)}
                <div class="feedback visible">
                  <b>Correct answer: ${escapeHtml(item.answer)}</b>
                  ${item.explanation ? `<div>${escapeHtml(item.explanation)}</div>` : ""}
                </div>
              </article>
            `
          )
          .join("")}
      </div>
    </div>
  `;
  $("#results-back", panel).addEventListener("click", () => {
    if (isHistory) {
      renderTestHistory();
      showView("history");
    } else {
      showView("dashboard");
    }
  });
}

function renderQuestion(panelSelector = "#test-panel") {
  const panel = $(panelSelector);
  const item = currentItem();
  const hasAnswer = hasSelectedAnswer(item);

  if (state.session?.status === "completed") {
    renderResults(panelSelector);
    return;
  }

  if (state.session && state.index >= state.session.count && state.session.count > 0) {
    completeCurrentSession(panelSelector);
    return;
  }

  if (!item) {
    panel.innerHTML = `
      <div class="empty-state">
        <div>
          <h3>No items ready</h3>
          <p>Add source material or check another area.</p>
        </div>
      </div>
    `;
    loadAll();
    return;
  }

  const choices = item.choices || [];
  const mode = state.session.mode;
  const isLastQuestion = state.index + 1 >= state.session.count;
  panel.innerHTML = `
    <div class="question-shell">
      <div class="progress-line">
        <span>${domains[item.domain]} / ${mode === "review" ? "Review" : "Test"}</span>
        <span>${state.index + 1} of ${state.session.count}</span>
      </div>
      ${questionMeta(item)}
      <div class="prompt">${escapeHtml(item.question_prompt || item.prompt)}</div>
      ${promptImagesHtml(item)}
      ${
        item.self_grade
          ? `
            <label>
              Your answer
              <input id="typed-answer" autocomplete="off" value="${escapeHtml(
                item.selected_answer || ""
              )}">
            </label>
            <div class="self-grade-actions">
              <button id="save-typed-answer">${hasAnswer ? "Update Answer" : "Save Answer"}</button>
            </div>
          `
          : `
            <div class="choices">
              ${choices
                .map(
                  (choice, index) => {
                    const selected = normalize(choice) === normalize(item.selected_answer);
                    return `
                    <button class="choice ${selected ? "selected" : ""}" data-choice="${escapeHtml(choice)}">
                      <span>${escapeHtml(choiceDisplayText(choice, index))}</span>
                      ${choiceImageHtml(item, index)}
                    </button>
                  `;
                  }
                )
                .join("")}
            </div>
          `
      }
      <div class="actions">
        <button id="prev-question" class="secondary" ${
          state.index <= 0 ? "disabled" : ""
        }>Back</button>
        <button id="next-question" ${hasAnswer ? "" : "disabled"}>${
    isLastQuestion ? "Finish" : "Next"
  }</button>
      </div>
    </div>
  `;

  if (item.self_grade) {
    const typedAnswer = $("#typed-answer", panel);
    const saveButton = $("#save-typed-answer", panel);
    const syncTypedControls = () => {
      const changed = normalize(typedAnswer.value) !== normalize(item.selected_answer);
      saveButton.disabled = !typedAnswer.value.trim() || !changed;
      $("#next-question", panel).disabled = !hasSelectedAnswer(item) || changed;
    };
    syncTypedControls();
    typedAnswer.addEventListener("input", syncTypedControls);
    typedAnswer.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !saveButton.disabled) {
        answerQuestion(typedAnswer.value, panelSelector);
      }
    });
    saveButton.addEventListener("click", () => {
      answerQuestion(typedAnswer.value, panelSelector);
    });
  } else {
    $$(".choice", panel).forEach((button) => {
      button.addEventListener("click", () => {
        const selected = button.dataset.choice;
        answerQuestion(selected, panelSelector);
      });
    });
  }

  $("#prev-question", panel).addEventListener("click", () => {
    if (state.index <= 0) return;
    state.index -= 1;
    renderQuestion(panelSelector);
  });

  $("#next-question", panel).addEventListener("click", () => {
    if (!hasSelectedAnswer(currentItem())) return;
    if (state.index + 1 >= state.session.count) {
      completeCurrentSession(panelSelector);
    } else {
      state.index += 1;
      renderQuestion(panelSelector);
    }
  });
}

function normalize(value) {
  return String(value || "").trim().replace(/\s+/g, " ").toLowerCase();
}

async function answerQuestion(selected, panelSelector) {
  const item = currentItem();
  if (!item) return;
  const panel = $(panelSelector);
  const currentPosition = item.position;
  const filters = state.session.filters;
  const requestedCount = state.session.requestedCount;

  $$(".choice", panel).forEach((button) => {
    const isSelected = normalize(button.dataset.choice) === normalize(selected);
    button.disabled = true;
    button.classList.toggle("selected", isSelected);
  });
  const typedAnswer = $("#typed-answer", panel);
  if (typedAnswer) typedAnswer.disabled = true;
  const saveButton = $("#save-typed-answer", panel);
  if (saveButton) saveButton.disabled = true;

  try {
    const saved = await api("/api/session/answer", {
      method: "POST",
      body: JSON.stringify({
        session_id: state.session.session_id,
        position: currentPosition,
        selected_answer: selected,
      }),
    });
    state.session = {
      ...saved,
      filters,
      requestedCount,
    };
    renderQuestion(panelSelector);
  } catch (error) {
    toast(error.message);
    renderQuestion(panelSelector);
  }
}

function renderFlashcard() {
  const panel = $("#flashcard-panel");
  if (state.session && state.index >= state.session.items.length && state.session.items.length > 0) {
    state.index = 0;
    state.flashPass += 1;
    prepareFlashDeck();
    toast(`Starting deck pass ${state.flashPass}.`);
  }
  const item = currentItem();
  state.flashFlipped = false;
  if (!item) {
    panel.innerHTML = `
      <div class="empty-state">
        <div>
          <h3>No vocabulary ready</h3>
          <p>Add vocabulary items before starting flashcards.</p>
        </div>
      </div>
    `;
    loadAll();
    return;
  }
  panel.innerHTML = `
    <div class="question-shell">
      <div class="progress-line">
        <span>${item.front_label} to ${item.back_label}</span>
        <span>Pass ${state.flashPass} / card ${state.index + 1} of ${state.session.items.length}</span>
      </div>
      <button class="flashcard" id="flip-card">
        <span>
          <div class="label">${escapeHtml(item.front_label)}</div>
          <div class="value">${escapeHtml(item.front)}</div>
        </span>
      </button>
      <div class="actions">
        <button id="flash-again" class="secondary" disabled>Again</button>
        <button id="flash-good">Next Word</button>
      </div>
    </div>
  `;

  $("#flip-card").addEventListener("click", () => {
    state.flashFlipped = !state.flashFlipped;
    const label = state.flashFlipped ? item.back_label : item.front_label;
    const value = state.flashFlipped ? item.back : item.front;
    $(".label", panel).textContent = label;
    $(".value", panel).textContent = value;
    $("#flash-again").disabled = false;
    $("#flash-good").disabled = false;
  });
  $("#flash-again").addEventListener("click", () => scoreFlashcard(false));
  $("#flash-good").addEventListener("click", () => scoreFlashcard(true));
}

async function scoreFlashcard(correct) {
  if (state.flashAdvancing) return;
  const item = currentItem();
  if (!item) return;
  state.flashAdvancing = true;
  try {
    await api("/api/attempts", {
      method: "POST",
      body: JSON.stringify({
        item_id: item.id,
        mode: "flashcards",
        selected_answer: correct ? "got it" : "again",
        correct,
      }),
    });
    rememberFlashcard(item);
    state.index += 1;
    renderFlashcard();
  } finally {
    state.flashAdvancing = false;
  }
}

function rememberFlashcard(item) {
  if (!item) return;
  state.flashHistory.push({ id: item.id, pass: state.flashPass });
  if (state.flashHistory.length > 100) {
    state.flashHistory.shift();
  }
}

function previousFlashcard() {
  if (state.flashAdvancing || state.session?.mode !== "flashcards" || !state.flashHistory.length) return;
  const previous = state.flashHistory.pop();
  const previousIndex = state.session.items.findIndex((item) => item.id === previous.id);
  if (previousIndex < 0) return;
  state.index = previousIndex;
  state.flashPass = previous.pass;
  renderFlashcard();
}

function isEditableTarget(target) {
  if (!(target instanceof HTMLElement)) return false;
  return Boolean(target.closest("input, select, textarea, [contenteditable='true']"));
}

function handleFlashcardKeys(event) {
  if ($(".view.active")?.id !== "flashcards" || isEditableTarget(event.target)) return;
  if (event.key === "ArrowRight") {
    event.preventDefault();
    scoreFlashcard(true);
  } else if (event.key === "ArrowLeft") {
    event.preventDefault();
    previousFlashcard();
  }
}

function formPayload(form) {
  return Object.fromEntries(new FormData(form).entries());
}

function bindEvents() {
  $$(".tab, [data-view]").forEach((button) => {
    button.addEventListener("click", () => showView(button.dataset.view));
  });

  $("#source-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = formPayload(event.currentTarget);
    await api("/api/sources", { method: "POST", body: JSON.stringify(payload) });
    event.currentTarget.reset();
    toast("Source added.");
    await loadAll();
  });

  $("#item-domain").addEventListener("change", syncItemFormForDomain);
  $("#import-domain").addEventListener("change", syncImportFormForDomain);

  $("#item-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = formPayload(event.currentTarget);
    payload.item_type = payload.domain === "vocabulary" ? "vocab" : "multiple_choice";
    payload.choices = payload.choices
      .split("\n")
      .map((choice) => choice.trim())
      .filter(Boolean);
    payload.prompt_images = (payload.prompt_images || "")
      .split("\n")
      .map((image) => image.trim())
      .filter(Boolean);
    payload.choice_images = (payload.choice_images || "")
      .split("\n")
      .map((image) => image.trim());
    await api("/api/items", { method: "POST", body: JSON.stringify(payload) });
    event.currentTarget.reset();
    $("#item-domain").value = payload.domain;
    syncItemFormForDomain();
    toast("Item added.");
    await loadAll();
  });

  $("#import-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = formPayload(event.currentTarget);
    const result = await api("/api/import", { method: "POST", body: JSON.stringify(payload) });
    toast(`Imported ${result.created} item${result.created === 1 ? "" : "s"}.`);
    if (result.errors?.length) {
      toast(`${result.created} imported; ${result.errors.length} line(s) skipped.`);
    }
    await loadAll();
  });

  $("#start-review").addEventListener("click", () => {
    startSession($("#review-domain").value, "review", "#review-panel");
  });

  $("#start-flashcards").addEventListener("click", () => {
    startSession("vocabulary", "flashcards", "#flashcard-panel");
  });

  document.addEventListener("keydown", handleFlashcardKeys);
}

window.addEventListener("error", (event) => {
  toast(event.message);
});

window.addEventListener("unhandledrejection", (event) => {
  toast(event.reason?.message || "Something went wrong.");
});

bindEvents();
loadAll();
