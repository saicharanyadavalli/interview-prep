const state = {
  companies: [],
  currentKey: "",
  currentQuestions: [],
  unseenIndices: [],
  seenCount: 0,
  poolSize: 0,
  lastQuestion: null,
  lastQuestionIndex: 0,
  theme: "light",
  isBusy: false,
  requestInFlight: false,
  chatInFlight: false,
  chatHistory: [],
  marked: [],
  revisit: [],
};

const BACKEND_ASK_URL = "http://127.0.0.1:8000/ask";

const companyInput = document.getElementById("companyInput");
const companyOptions = document.getElementById("companyOptions");
const difficultySelect = document.getElementById("difficultySelect");
const startBtn = document.getElementById("startBtn");
const nextBtn = document.getElementById("nextBtn");
const recommendBtn = document.getElementById("recommendBtn");
const resetBtn = document.getElementById("resetBtn");
const surpriseBtn = document.getElementById("surpriseBtn");
const copyBtn = document.getElementById("copyBtn");
const filterInput = document.getElementById("filterInput");
const themeToggleBtn = document.getElementById("themeToggleBtn");
const statusText = document.getElementById("statusText");
const counterBadge = document.getElementById("counterBadge");
const questionCard = document.getElementById("questionCard");
const progressFill = document.getElementById("progressFill");
const feedbackStrong = document.getElementById("feedbackStrong");
const feedbackGood = document.getElementById("feedbackGood");
const feedbackRevisit = document.getElementById("feedbackRevisit");
const feedbackSkip = document.getElementById("feedbackSkip");
const clearCollectionsBtn = document.getElementById("clearCollectionsBtn");
const markedCount = document.getElementById("markedCount");
const revisitCount = document.getElementById("revisitCount");
const markedList = document.getElementById("markedList");
const revisitList = document.getElementById("revisitList");
const feedbackButtons = [feedbackStrong, feedbackGood, feedbackRevisit, feedbackSkip];

const qTitle = document.getElementById("qTitle");
const qIndex = document.getElementById("qIndex");
const qDifficulty = document.getElementById("qDifficulty");
const qProblemUrl = document.getElementById("qProblemUrl");
const qStatement = document.getElementById("qStatement");
const examplesArticle = document.getElementById("examplesArticle");
const qExamples = document.getElementById("qExamples");
const qTags = document.getElementById("qTags");
const qConstraints = document.getElementById("qConstraints");
const qRaw = document.getElementById("qRaw");
const chatMessages = document.getElementById("chatMessages");
const doubtInput = document.getElementById("doubtInput");
const sendDoubtBtn = document.getElementById("sendDoubtBtn");
const clearChatBtn = document.getElementById("clearChatBtn");

function setStatus(message) {
  statusText.textContent = message;
}

function updateCounter() {
  counterBadge.textContent = `${state.seenCount} / ${state.poolSize}`;
  const denominator = state.poolSize || 1;
  const progress = Math.min((state.seenCount / denominator) * 100, 100);
  progressFill.style.width = `${progress}%`;
}

function getErrorMessage(error) {
  return error instanceof Error ? error.message : String(error);
}

function getCurrentInterviewQuestionText() {
  if (!state.lastQuestion) {
    return "";
  }
  const { core } = normalizeQuestion(state.lastQuestion);
  const title = core.problem_name || "Untitled Question";
  const statement = core.statement_text || core.full_text || "";
  const constraints = core.constraints_text || "";
  return `Title: ${title}\n\nStatement:\n${statement}\n\nConstraints:\n${constraints}`.trim();
}

function addChatMessage(role, content) {
  state.chatHistory.push({ role, content: String(content || "").trim() });
}

function normalizeAssistantText(text) {
  let normalized = String(text || "").replace(/\r\n?/g, "\n");

  normalized = normalized
    .replace(/```[\s\S]*?```/g, (block) => block.replace(/```/g, "").trim())
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/__([^_]+)__/g, "$1")
    .replace(/^\s*\*\s+/gm, "- ")
    .replace(/^\s*[-+]\s+/gm, "- ")
    .replace(/\n{3,}/g, "\n\n")
    .trim();

  return normalized;
}

function renderChat() {
  chatMessages.innerHTML = "";

  if (!state.chatHistory.length) {
    const empty = document.createElement("p");
    empty.className = "chat-empty";
    empty.textContent = "Start by loading a question, then ask your doubt.";
    chatMessages.appendChild(empty);
    return;
  }

  state.chatHistory.forEach((item) => {
    const bubble = document.createElement("article");
    bubble.className = `chat-bubble ${item.role === "assistant" ? "assistant" : "user"}`;

    const head = document.createElement("p");
    head.className = "chat-role";
    head.textContent = item.role === "assistant" ? "Assistant" : "You";

    const body = document.createElement("p");
    body.className = "chat-text";
    body.textContent = item.role === "assistant" ? normalizeAssistantText(item.content) : item.content;

    bubble.appendChild(head);
    bubble.appendChild(body);
    chatMessages.appendChild(bubble);
  });

  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function updateChatControls() {
  const hasQuestion = Boolean(state.lastQuestion);
  sendDoubtBtn.disabled = !hasQuestion || state.chatInFlight;
  doubtInput.disabled = !hasQuestion || state.chatInFlight;
}

async function askAssistantFromCurrentQuestion() {
  if (state.chatInFlight) {
    return;
  }

  const questionText = getCurrentInterviewQuestionText();
  if (!questionText) {
    setStatus("Load a question before asking a doubt.");
    updateChatControls();
    return;
  }

  const doubt = doubtInput.value.trim();
  if (!doubt) {
    setStatus("Type your doubt first.");
    return;
  }

  addChatMessage("user", doubt);
  renderChat();
  doubtInput.value = "";
  state.chatInFlight = true;
  updateChatControls();
  setStatus("Asking assistant...");

  try {
    const response = await fetch(BACKEND_ASK_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        interview_question: questionText,
        user_doubt: doubt,
        conversation_history: state.chatHistory.slice(-12),
      }),
    });

    if (!response.ok) {
      throw new Error(`Backend returned ${response.status}`);
    }

    const data = await response.json();
    const answer = typeof data.answer === "string" ? data.answer.trim() : "No answer returned.";
    addChatMessage("assistant", answer || "No answer returned.");
    renderChat();
    setStatus("Assistant responded.");
  } catch (error) {
    const msg = getErrorMessage(error);
    addChatMessage(
      "assistant",
      `I could not reach the backend right now. Please ensure FastAPI is running on ${BACKEND_ASK_URL}. Error: ${msg}`
    );
    renderChat();
    setStatus(`Chat error: ${msg}`);
  } finally {
    state.chatInFlight = false;
    updateChatControls();
  }
}

function clearChat() {
  state.chatHistory = [];
  renderChat();
  setStatus("Conversation cleared.");
}

function savePreferences() {
  const payload = {
    company: companyInput.value.trim(),
    difficulty: difficultySelect.value,
    filter: filterInput.value.trim(),
    theme: state.theme,
  };
  localStorage.setItem("interviewAssistantPreferences", JSON.stringify(payload));
}

function applyTheme(theme) {
  state.theme = theme === "dark" ? "dark" : "light";
  document.body.setAttribute("data-theme", state.theme);
  themeToggleBtn.textContent = state.theme === "dark" ? "Light Mode" : "Dark Mode";
  savePreferences();
}

function toggleTheme() {
  applyTheme(state.theme === "dark" ? "light" : "dark");
}

function loadPreferences() {
  const raw = localStorage.getItem("interviewAssistantPreferences");
  if (!raw) {
    applyTheme("light");
    return;
  }
  try {
    const parsed = JSON.parse(raw);
    if (parsed.difficulty) {
      difficultySelect.value = parsed.difficulty;
    }
    if (parsed.filter) {
      filterInput.value = parsed.filter;
    }
    applyTheme(parsed.theme || "light");
    if (parsed.company) {
      companyInput.value = parsed.company;
    }
  } catch (error) {
    applyTheme("light");
  }
}

function saveCollections() {
  localStorage.setItem(
    "interviewAssistantUserCollections",
    JSON.stringify({ marked: state.marked, revisit: state.revisit })
  );
}

function loadCollections() {
  const raw = localStorage.getItem("interviewAssistantUserCollections");
  if (!raw) {
    state.marked = [];
    state.revisit = [];
    renderCollections();
    return;
  }
  try {
    const parsed = JSON.parse(raw);
    state.marked = Array.isArray(parsed.marked) ? parsed.marked : [];
    state.revisit = Array.isArray(parsed.revisit) ? parsed.revisit : [];
  } catch (error) {
    state.marked = [];
    state.revisit = [];
  }
  renderCollections();
}

function normalizeQuestion(item) {
  const wrapped = item && typeof item === "object" && item.problem_page ? item.problem_page : item;
  return {
    raw: item,
    core: wrapped || {},
  };
}

function parseArray(value) {
  if (!value) {
    return [];
  }
  if (Array.isArray(value)) {
    return value;
  }
  return [String(value)];
}

function createChip(text) {
  const span = document.createElement("span");
  span.className = "chip";
  span.textContent = text;
  return span;
}

function splitStatementExamples(statementText) {
  const text = String(statementText || "").replace(/\r\n?/g, "\n");
  const match = text.match(/\n?\s*Examples?\s*:/i);
  if (!match || typeof match.index !== "number") {
    return { statementOnly: text.trim(), examplesTail: "" };
  }
  const start = match.index;
  return {
    statementOnly: text.slice(0, start).trim(),
    examplesTail: text.slice(start).trim(),
  };
}

function normalizeExampleText(exampleText) {
  let text = String(exampleText || "").replace(/\r\n?/g, "\n").trim();
  text = text.replace(/^Examples?\s*:/i, "").trim();
  text = text.replace(/\bInput\s*:\s*/gi, "Input:\n");
  text = text.replace(/\bOutput\s*:\s*/gi, "\nOutput:\n");
  text = text.replace(/\bExplanation\s*:\s*/gi, "\nExplanation:\n");
  text = text.replace(/\bExplaination\s*:\s*/gi, "\nExplaination:\n");
  text = text.replace(/\n{3,}/g, "\n\n");
  return text.trim();
}

function splitExamplesToBlocks(rawText) {
  const text = String(rawText || "").replace(/\r\n?/g, "\n").trim();
  if (!text) {
    return [];
  }

  const byExampleHeading = text
    .split(/(?=\bExample\s*\d+\s*:)/i)
    .map((part) => part.trim())
    .filter(Boolean);

  if (byExampleHeading.length > 1) {
    return byExampleHeading.map((part) => normalizeExampleText(part));
  }

  const byInputHeading = text
    .split(/(?=\bInput\s*:)/i)
    .map((part) => part.trim())
    .filter(Boolean);

  if (byInputHeading.length > 1) {
    return byInputHeading.map((part) => normalizeExampleText(part));
  }

  return [normalizeExampleText(text)];
}

function prepareExamples(core, statementExamplesTail) {
  const sourceExamples = parseArray(core.examples)
    .map((item) => String(item || "").trim())
    .filter(Boolean);

  let blocks = sourceExamples.flatMap((item) => splitExamplesToBlocks(item));

  if (blocks.length === 0 && statementExamplesTail) {
    blocks = splitExamplesToBlocks(statementExamplesTail);
  }

  const cleaned = blocks
    .map((block) => normalizeExampleText(block))
    .filter(Boolean);

  return cleaned;
}

function hasTreeTag(core) {
  const tags = [...parseArray(core.topic_tags), ...parseArray(core.company_tags)]
    .map((tag) => String(tag || "").toLowerCase());

  return tags.some((tag) => tag.includes("binary tree") || tag.includes("tree"));
}

function questionId(item) {
  const { core } = normalizeQuestion(item);
  return core.slug || core.problem_url || core.problem_name || "unknown";
}

function questionRecord(item, label) {
  const { core, raw } = normalizeQuestion(item);
  return {
    id: questionId(item),
    title: core.problem_name || "Untitled Question",
    url: core.problem_url || "",
    difficulty: core.difficulty || label || "Unknown",
    addedAt: new Date().toISOString(),
    raw,
  };
}

function renderTrackList(listEl, countEl, entries, type) {
  listEl.innerHTML = "";
  countEl.textContent = String(entries.length);

  if (!entries.length) {
    const empty = document.createElement("li");
    empty.className = "track-empty";
    empty.textContent = type === "marked" ? "No marked questions yet." : "No revisit questions yet.";
    listEl.appendChild(empty);
    return;
  }

  entries.forEach((entry, idx) => {
    const li = document.createElement("li");
    li.className = "track-item";

    const left = document.createElement("div");
    left.className = "track-item-main";

    const title = document.createElement("p");
    title.className = "track-title";
    title.textContent = `#${idx + 1} ${entry.title}`;

    const meta = document.createElement("p");
    meta.className = "track-meta";
    meta.textContent = `${entry.difficulty} | ${new Date(entry.addedAt).toLocaleDateString()}`;

    left.appendChild(title);
    left.appendChild(meta);

    const actions = document.createElement("div");
    actions.className = "track-actions";

    const practiceBtn = document.createElement("button");
    practiceBtn.className = "btn";
    practiceBtn.type = "button";
    practiceBtn.textContent = "Practice";
    practiceBtn.dataset.type = type;
    practiceBtn.dataset.index = String(idx);
    practiceBtn.dataset.action = "practice";

    const removeBtn = document.createElement("button");
    removeBtn.className = "btn";
    removeBtn.type = "button";
    removeBtn.textContent = "Remove";
    removeBtn.dataset.type = type;
    removeBtn.dataset.index = String(idx);
    removeBtn.dataset.action = "remove";

    actions.appendChild(practiceBtn);
    actions.appendChild(removeBtn);

    li.appendChild(left);
    li.appendChild(actions);
    listEl.appendChild(li);
  });
}

function renderCollections() {
  renderTrackList(markedList, markedCount, state.marked, "marked");
  renderTrackList(revisitList, revisitCount, state.revisit, "revisit");
}

function upsertCollection(type, record) {
  const target = type === "marked" ? state.marked : state.revisit;
  const existingIndex = target.findIndex((item) => item.id === record.id);
  if (existingIndex >= 0) {
    target[existingIndex] = record;
  } else {
    target.unshift(record);
  }
}

function removeFromCollection(type, id) {
  if (type === "marked") {
    state.marked = state.marked.filter((item) => item.id !== id);
  } else {
    state.revisit = state.revisit.filter((item) => item.id !== id);
  }
}

function setFeedbackButtonsEnabled(enabled) {
  feedbackStrong.disabled = !enabled;
  feedbackGood.disabled = !enabled;
  feedbackRevisit.disabled = !enabled;
  feedbackSkip.disabled = !enabled;
}

function clearFeedbackSelection() {
  feedbackButtons.forEach((btn) => btn.classList.remove("btn-feedback-selected"));
}

function setFeedbackSelection(button) {
  clearFeedbackSelection();
  button.classList.add("btn-feedback-selected");
}

function renderQuestion(item, indexLabel) {
  const { raw, core } = normalizeQuestion(item);
  const difficulty = core.difficulty || item.stage2_difficulty || "Unknown";
  const title = core.problem_name || item.problem_name || "Untitled Question";
  const problemUrl = core.problem_url || item.problem_url || "#";

  qTitle.textContent = title;
  qIndex.textContent = `Question #${indexLabel}`;
  qDifficulty.textContent = `Difficulty: ${difficulty}`;
  qProblemUrl.href = problemUrl;
  qProblemUrl.textContent = problemUrl === "#" ? "No problem URL" : "Open Problem";

  const statementSource = core.statement_text || core.full_text || "No statement available.";
  const split = splitStatementExamples(statementSource);
  const preserveExamplesInStatement = hasTreeTag(core);
  qStatement.textContent = preserveExamplesInStatement
    ? String(statementSource || "No statement available.").trim()
    : split.statementOnly || "No statement available.";
  qConstraints.textContent = core.constraints_text || "No constraints available.";

  qExamples.innerHTML = "";
  qExamples.classList.add("example-list");
  const examples = prepareExamples(core, preserveExamplesInStatement ? "" : split.examplesTail);
  if (examples.length === 0) {
    examplesArticle.classList.add("hidden");
  } else {
    examplesArticle.classList.remove("hidden");
    examples.forEach((e) => {
      const pre = document.createElement("pre");
      pre.className = "example-block";
      pre.textContent = String(e);
      qExamples.appendChild(pre);
    });
  }

  qTags.innerHTML = "";
  const tags = [...parseArray(core.topic_tags), ...parseArray(core.company_tags)];
  if (tags.length === 0) {
    qTags.appendChild(createChip("No tags"));
  } else {
    const unique = [...new Set(tags)];
    unique.forEach((tag) => qTags.appendChild(createChip(tag)));
  }

  qRaw.textContent = JSON.stringify(raw, null, 2);
  questionCard.classList.remove("hidden");
  questionCard.scrollIntoView({ behavior: "smooth", block: "start" });
}

function shuffle(array) {
  const cloned = [...array];
  for (let i = cloned.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [cloned[i], cloned[j]] = [cloned[j], cloned[i]];
  }
  return cloned;
}

function companyExists(name) {
  return state.companies.some((company) => company.toLowerCase() === name.toLowerCase());
}

function canonicalCompany(name) {
  return state.companies.find((company) => company.toLowerCase() === name.toLowerCase()) || name;
}

async function fetchQuestions(company, difficulty) {
  const path = `../output/stage3_company_wise/${encodeURIComponent(company)}/questions_detailed_${difficulty}.json`;
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`Failed to load ${path}`);
  }
  const data = await response.json();
  if (!Array.isArray(data)) {
    throw new Error("Invalid JSON structure. Expected an array.");
  }
  return data;
}

function filteredQuestionIndices() {
  const filter = filterInput.value.trim().toLowerCase();
  if (!filter) {
    return state.currentQuestions.map((_, idx) => idx);
  }

  return state.currentQuestions
    .map((question, idx) => ({ idx, question }))
    .filter(({ question }) => {
      const { core } = normalizeQuestion(question);
      const haystack = [
        core.problem_name,
        core.statement_text,
        ...(Array.isArray(core.topic_tags) ? core.topic_tags : []),
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(filter);
    })
    .map(({ idx }) => idx);
}

function resetUnseenFromFilter() {
  const indices = filteredQuestionIndices();
  state.unseenIndices = shuffle(indices);
  state.poolSize = indices.length;
  state.seenCount = 0;
  state.lastQuestion = null;
  state.lastQuestionIndex = 0;
  updateChatControls();
  copyBtn.disabled = true;
  setFeedbackButtonsEnabled(false);
  updateCounter();
}

async function startSession(resetOnly = false) {
  if (state.requestInFlight) {
    return;
  }

  const company = canonicalCompany(companyInput.value.trim());
  const difficulty = difficultySelect.value;

  if (!company) {
    setStatus("Please enter a company name.");
    return;
  }
  if (!companyExists(company)) {
    setStatus("Company not found. Please pick from available companies.");
    return;
  }

  companyInput.value = company;
  savePreferences();

  const key = `${company}::${difficulty}`;
  const needsReload = !resetOnly || state.currentKey !== key;

  if (needsReload) {
    try {
      state.requestInFlight = true;
      setStatus("Loading questions...");
      const questions = await fetchQuestions(company, difficulty);
      state.currentKey = key;
      state.currentQuestions = questions;
      resetUnseenFromFilter();

      if (questions.length === 0) {
        setStatus(`No ${difficulty} questions found for ${company}.`);
        questionCard.classList.add("hidden");
        nextBtn.disabled = true;
        recommendBtn.disabled = true;
        resetBtn.disabled = true;
        state.poolSize = 0;
        updateChatControls();
        updateCounter();
        return;
      }

      setStatus(`Loaded ${questions.length} ${difficulty} questions for ${company}.`);
      nextBtn.disabled = false;
      recommendBtn.disabled = false;
      resetBtn.disabled = false;
      showNextQuestion();
    } catch (error) {
      setStatus(`Error: ${getErrorMessage(error)}`);
      questionCard.classList.add("hidden");
      nextBtn.disabled = true;
      recommendBtn.disabled = true;
      resetBtn.disabled = true;
      copyBtn.disabled = true;
      updateChatControls();
      setFeedbackButtonsEnabled(false);
      state.poolSize = 0;
      updateCounter();
    } finally {
      state.requestInFlight = false;
    }
    return;
  }

  resetUnseenFromFilter();
  setStatus("Question order reset for current company and difficulty.");
  nextBtn.disabled = false;
  recommendBtn.disabled = false;
  showNextQuestion();
}

function showSpecificQuestion(item, sourceLabel) {
  state.lastQuestion = item;
  state.lastQuestionIndex = sourceLabel;
  copyBtn.disabled = false;
  setFeedbackButtonsEnabled(true);
  updateChatControls();
  clearFeedbackSelection();
  renderQuestion(item, sourceLabel);
}

function showNextQuestion() {
  if (!state.currentQuestions.length) {
    setStatus("No loaded questions. Click Load Random Question first.");
    return;
  }

  if (state.unseenIndices.length === 0) {
    setStatus("All questions shown once. Click Reset Set to reshuffle.");
    nextBtn.disabled = true;
    recommendBtn.disabled = true;
    return;
  }

  const nextIndex = state.unseenIndices.pop();
  const nextQuestion = state.currentQuestions[nextIndex];
  state.seenCount += 1;
  state.lastQuestion = nextQuestion;
  state.lastQuestionIndex = state.seenCount;
  updateCounter();
  renderQuestion(nextQuestion, state.seenCount);
  copyBtn.disabled = false;
  setFeedbackButtonsEnabled(true);
  updateChatControls();
  clearFeedbackSelection();

  if (state.unseenIndices.length === 0) {
    setStatus("Last new question shown. No repeats left in this set.");
    nextBtn.disabled = true;
    recommendBtn.disabled = true;
  } else {
    setStatus(`${state.unseenIndices.length} unseen questions remaining in this set.`);
    nextBtn.disabled = false;
    recommendBtn.disabled = false;
  }
}

function recommendNextQuestion() {
  if (!state.unseenIndices.length) {
    setStatus("No unseen questions left to recommend.");
    recommendBtn.disabled = true;
    return;
  }

  const revisitIds = new Set(state.revisit.map((item) => item.id));
  const revisitCandidate = state.unseenIndices.find((idx) => revisitIds.has(questionId(state.currentQuestions[idx])));

  if (revisitCandidate !== undefined) {
    state.unseenIndices = state.unseenIndices.filter((idx) => idx !== revisitCandidate);
    const question = state.currentQuestions[revisitCandidate];
    state.seenCount += 1;
    state.lastQuestion = question;
    state.lastQuestionIndex = state.seenCount;
    updateCounter();
    renderQuestion(question, state.seenCount);
    copyBtn.disabled = false;
    setFeedbackButtonsEnabled(true);
    setStatus("Recommended from your revisit queue.");
    if (!state.unseenIndices.length) {
      nextBtn.disabled = true;
      recommendBtn.disabled = true;
    }
    return;
  }

  showNextQuestion();
}

function addCurrentToCollection(type, sourceButton = null) {
  if (!state.lastQuestion) {
    setStatus("Load a question first.");
    return;
  }

  const record = questionRecord(state.lastQuestion, difficultySelect.value);

  if (type === "revisit") {
    setFeedbackSelection(feedbackRevisit);
    upsertCollection("revisit", record);
    removeFromCollection("marked", record.id);
    setStatus("Added to Revisit Queue.");
  } else if (type === "marked") {
    setFeedbackSelection(sourceButton || feedbackStrong);
    upsertCollection("marked", record);
    removeFromCollection("revisit", record.id);
    setStatus("Added to Marked Questions.");
  } else {
    setFeedbackSelection(feedbackSkip);
    setStatus("Skipped current question.");
    showNextQuestion();
    return;
  }

  saveCollections();
  renderCollections();
}

function clearCollections() {
  state.marked = [];
  state.revisit = [];
  saveCollections();
  renderCollections();
  setStatus("Marked and Revisit lists cleared.");
}

function copyCurrentQuestionLink() {
  if (!state.lastQuestion) {
    setStatus("Load a question before copying link.");
    return;
  }
  const { core } = normalizeQuestion(state.lastQuestion);
  const link = core.problem_url || "";
  if (!link) {
    setStatus("No link available for this question.");
    return;
  }
  navigator.clipboard
    .writeText(link)
    .then(() => setStatus("Question link copied to clipboard."))
    .catch(() => setStatus("Could not copy link. Browser blocked clipboard access."));
}

function pickSurpriseCompany() {
  if (!state.companies.length) {
    return;
  }
  const randomIndex = Math.floor(Math.random() * state.companies.length);
  companyInput.value = state.companies[randomIndex];
  savePreferences();
  setStatus(`Surprise company selected: ${state.companies[randomIndex]}`);
}

async function loadCompanies() {
  try {
    const response = await fetch("./companies.json");
    if (!response.ok) {
      throw new Error("Failed to load company list.");
    }

    const companies = await response.json();
    if (!Array.isArray(companies)) {
      throw new Error("Company list JSON is invalid.");
    }

    state.companies = companies;
    companyOptions.innerHTML = "";

    companies.forEach((name) => {
      const option = document.createElement("option");
      option.value = name;
      companyOptions.appendChild(option);
    });

    if (companies.length > 0 && !companyInput.value.trim()) {
      companyInput.value = companies[0];
    }

    setStatus(`Ready. ${companies.length} companies loaded.`);
  } catch (error) {
    setStatus(`Error: ${getErrorMessage(error)}`);
  }
}

async function runGuarded(action) {
  if (state.isBusy) {
    return;
  }
  state.isBusy = true;
  try {
    await action();
  } finally {
    setTimeout(() => {
      state.isBusy = false;
    }, 180);
  }
}

function handleTrackListAction(event) {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }

  const action = target.dataset.action;
  const type = target.dataset.type;
  const rawIndex = target.dataset.index;

  if (!action || !type || rawIndex == null) {
    return;
  }

  const index = Number(rawIndex);
  const source = type === "marked" ? state.marked : state.revisit;
  const entry = source[index];
  if (!entry) {
    return;
  }

  if (action === "practice") {
    showSpecificQuestion(entry.raw, `Saved ${type === "marked" ? "Marked" : "Revisit"} #${index + 1}`);
    setStatus(`Loaded saved question from ${type} list.`);
  }

  if (action === "remove") {
    source.splice(index, 1);
    saveCollections();
    renderCollections();
    setStatus("Removed from saved list.");
  }
}

startBtn.addEventListener("click", () => runGuarded(() => startSession(false)));
nextBtn.addEventListener("click", () => runGuarded(() => showNextQuestion()));
recommendBtn.addEventListener("click", () => runGuarded(() => recommendNextQuestion()));
resetBtn.addEventListener("click", () => runGuarded(() => startSession(true)));
themeToggleBtn.addEventListener("click", toggleTheme);
copyBtn.addEventListener("click", () => runGuarded(() => copyCurrentQuestionLink()));
surpriseBtn.addEventListener("click", () => runGuarded(() => pickSurpriseCompany()));
feedbackStrong.addEventListener("click", () => runGuarded(() => addCurrentToCollection("marked", feedbackStrong)));
feedbackGood.addEventListener("click", () => {
  runGuarded(() => addCurrentToCollection("marked", feedbackGood));
});
feedbackRevisit.addEventListener("click", () => runGuarded(() => addCurrentToCollection("revisit")));
feedbackSkip.addEventListener("click", () => runGuarded(() => addCurrentToCollection("skip")));
clearCollectionsBtn.addEventListener("click", () => runGuarded(() => clearCollections()));
markedList.addEventListener("click", handleTrackListAction);
revisitList.addEventListener("click", handleTrackListAction);

filterInput.addEventListener("input", () => {
  if (!state.currentQuestions.length) {
    savePreferences();
    return;
  }
  resetUnseenFromFilter();
  nextBtn.disabled = state.unseenIndices.length === 0;
  recommendBtn.disabled = state.unseenIndices.length === 0;
  savePreferences();
  setStatus(
    state.unseenIndices.length
      ? `${state.unseenIndices.length} questions match current filter.`
      : "No questions match current filter."
  );
});

companyInput.addEventListener("change", savePreferences);
difficultySelect.addEventListener("change", savePreferences);

document.addEventListener("keydown", (event) => {
  if (event.target && ["INPUT", "TEXTAREA", "SELECT"].includes(event.target.tagName)) {
    return;
  }
  const key = event.key.toLowerCase();
  if (key === "n" && !nextBtn.disabled) {
    runGuarded(() => showNextQuestion());
  }
  if (key === "r" && !recommendBtn.disabled) {
    runGuarded(() => recommendNextQuestion());
  }
  if (key === "l") {
    runGuarded(() => startSession(false));
  }
  if (key === "t") {
    toggleTheme();
  }
});

loadPreferences();
loadCollections();
loadCompanies();
renderChat();
updateChatControls();

sendDoubtBtn.addEventListener("click", () => runGuarded(() => askAssistantFromCurrentQuestion()));
clearChatBtn.addEventListener("click", () => runGuarded(() => clearChat()));
doubtInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    runGuarded(() => askAssistantFromCurrentQuestion());
  }
});
