/**
 * practice.js — Unified question solving page.
 *
 * Supports direct links from question lists, sequential navigation,
 * progress actions, notes, local ratings, and AI assistant.
 */

const practiceState = {
  companies: [],
  currentQuestions: [],
  currentIndex: -1,
  poolSize: 0,
  userLoggedIn: false,
  isBusy: false,
  chatInFlight: false,
  chatHistory: [],
  lastQuestion: null,
  progress: { outcome: null, revisit: false },
};

document.addEventListener("DOMContentLoaded", async () => {
  const user = await initSidebar("practice", { requireLogin: true });
  if (!user) {
    return;
  }
  practiceState.userLoggedIn = Boolean(user);
  if (user) {
    const { session } = await getSession();
    if (session) await syncSessionWithBackend(session.access_token);
  }
  initPractice();
});

async function initPractice() {
  const companyInput = document.getElementById("companyInput");
  const companyOptions = document.getElementById("companyOptions");
  const difficultySelect = document.getElementById("difficultySelect");
  const startBtn = document.getElementById("startBtn");
  const prevBtn = document.getElementById("prevBtn");
  const nextBtn = document.getElementById("nextBtn");
  const recommendBtn = document.getElementById("recommendBtn");
  const resetBtn = document.getElementById("resetBtn");
  const surpriseBtn = document.getElementById("surpriseBtn");
  const copyBtn = document.getElementById("copyBtn");
  const statusText = document.getElementById("statusText");
  const counterBadge = document.getElementById("counterBadge");
  const questionCard = document.getElementById("questionCard");
  const progressFill = document.getElementById("progressFill");

  const markSolvedBtn = document.getElementById("markSolvedBtn");
  const markUnsolvedBtn = document.getElementById("markUnsolvedBtn");
  const markRevisitBtn = document.getElementById("markRevisitBtn");

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

  const commentsList = document.getElementById("commentsList");
  const commentInput = document.getElementById("commentInput");
  const addCommentBtn = document.getElementById("addCommentBtn");

  const chatMessages = document.getElementById("chatMessages");
  const doubtInput = document.getElementById("doubtInput");
  const sendDoubtBtn = document.getElementById("sendDoubtBtn");
  const clearChatBtn = document.getElementById("clearChatBtn");

  function showToast(msg, type = "info") {
    let toast = document.getElementById("toast");
    if (!toast) {
      toast = document.createElement("div");
      toast.id = "toast";
      document.body.appendChild(toast);
    }
    toast.textContent = msg;
    toast.className = `toast toast-${type} toast-show`;
    setTimeout(() => toast.classList.remove("toast-show"), 2600);
  }

  function setStatus(msg) {
    if (statusText) statusText.textContent = msg;
  }

  function updateCounter() {
    const seen = practiceState.currentIndex >= 0 ? practiceState.currentIndex + 1 : 0;
    if (counterBadge) counterBadge.textContent = `${seen} / ${practiceState.poolSize}`;
    if (progressFill) {
      const pct = practiceState.poolSize ? Math.min((seen / practiceState.poolSize) * 100, 100) : 0;
      progressFill.style.width = `${pct}%`;
    }
  }

  function setQuestionControlsEnabled(on) {
    [prevBtn, nextBtn, recommendBtn, copyBtn, markSolvedBtn, markUnsolvedBtn, markRevisitBtn].forEach((btn) => {
      if (btn) btn.disabled = !on;
    });
  }

  function updateNavButtons() {
    if (!prevBtn || !nextBtn) return;
    const has = practiceState.poolSize > 0;
    prevBtn.disabled = !has || practiceState.currentIndex <= 0;
    nextBtn.disabled = !has || practiceState.currentIndex >= practiceState.poolSize - 1;
  }

  function updateChatControls() {
    const hasQ = Boolean(practiceState.lastQuestion);
    if (sendDoubtBtn) sendDoubtBtn.disabled = !hasQ || practiceState.chatInFlight;
    if (doubtInput) doubtInput.disabled = !hasQ || practiceState.chatInFlight;
  }

  function clearOutcomeSelection() {
    [markSolvedBtn, markUnsolvedBtn, markRevisitBtn].forEach((btn) => {
      if (btn) btn.classList.remove("btn-feedback-selected");
    });
  }

  function normalizeProgressState(data) {
    const legacy = String(data?.status || "").toLowerCase();
    let outcome = String(data?.outcome || "").toLowerCase();
    let revisit = Boolean(data?.revisit);

    if (!legacy && !outcome && !revisit) {
      return { outcome: null, revisit: false };
    }

    if (outcome !== "solved" && outcome !== "unsolved") {
      if (legacy === "good" || legacy === "strong") {
        outcome = "solved";
      } else if (legacy === "skip" || legacy === "revisit") {
        outcome = "unsolved";
      } else {
        outcome = null;
      }
    }

    if (!data || data.revisit === undefined) {
      revisit = legacy === "revisit";
    }

    return { outcome, revisit };
  }

  function applyOutcomeSelection(progressState) {
    clearOutcomeSelection();
    const state = normalizeProgressState(progressState || {});
    practiceState.progress = state;

    if (state.outcome === "solved") {
      markSolvedBtn?.classList.add("btn-feedback-selected");
    } else if (state.outcome === "unsolved") {
      markUnsolvedBtn?.classList.add("btn-feedback-selected");
    }

    if (state.revisit) {
      markRevisitBtn?.classList.add("btn-feedback-selected");
    }

    if (markRevisitBtn) {
      markRevisitBtn.textContent = state.revisit ? "↩️ Remove From Revisit" : "🔄 Add To Revisit";
    }
  }

  async function syncOutcomeFromDatabase() {
    clearOutcomeSelection();
    const q = practiceState.lastQuestion;
    if (!q || !practiceState.userLoggedIn) return;

    try {
      const data = await API.getProgressStatus(q.qnum);
      applyOutcomeSelection(data || null);
    } catch (_) {
      // Keep neutral button state if status lookup fails.
    }
  }

  function parseArray(v) {
    return Array.isArray(v) ? v : v ? [String(v)] : [];
  }

  function createChip(text) {
    const span = document.createElement("span");
    span.className = "chip";
    span.textContent = text;
    return span;
  }

  function splitStatementExamples(text) {
    const s = String(text || "").replace(/\r\n?/g, "\n");
    const m = s.match(/\n?\s*Examples?\s*:/i);
    if (!m || typeof m.index !== "number") return { statement: s.trim(), tail: "" };
    return { statement: s.slice(0, m.index).trim(), tail: s.slice(m.index).trim() };
  }

  function splitExamples(rawText) {
    const text = String(rawText || "").replace(/\r\n?/g, "\n").trim();
    if (!text) return [];
    const byHeading = text.split(/(?=\bExample\s*\d+\s*:)/i).map((s) => s.trim()).filter(Boolean);
    if (byHeading.length > 1) return byHeading;
    const byInput = text.split(/(?=\bInput\s*:)/i).map((s) => s.trim()).filter(Boolean);
    if (byInput.length > 1) return byInput;
    return [text];
  }

  function normalizeAssistantText(text) {
    return String(text || "")
      .replace(/\r\n?/g, "\n")
      .replace(/```[\s\S]*?```/g, (b) => b.replace(/```/g, "").trim())
      .replace(/`([^`]+)`/g, "$1")
      .replace(/\*\*([^*]+)\*\*/g, "$1")
      .replace(/\n{3,}/g, "\n\n")
      .trim();
  }

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text || "";
    return div.innerHTML;
  }

  function formatDate(dateStr) {
    if (!dateStr) return "";
    try {
      return new Date(dateStr).toLocaleDateString();
    } catch (_) {
      return dateStr;
    }
  }

  function syncUrlWithQuestion(q) {
    if (!q) return;
    const params = new URLSearchParams(window.location.search);
    if (companyInput && companyInput.value.trim()) params.set("company", companyInput.value.trim());
    if (difficultySelect && difficultySelect.value) params.set("difficulty", difficultySelect.value);
    if (q.qnum) params.set("qnum", String(q.qnum));
    const nextUrl = `${window.location.pathname}?${params.toString()}`;
    window.history.replaceState({}, "", nextUrl);
  }

  async function loadCommentsForCurrentQuestion() {
    const q = practiceState.lastQuestion;
    if (!q || !commentsList) return;

    if (!practiceState.userLoggedIn) {
      commentsList.innerHTML = '<p class="text-muted text-sm">Sign in to sync notes.</p>';
      if (commentInput) commentInput.value = "";
      return;
    }

    commentsList.innerHTML = '<p class="loading"><span class="loading-dot">⏳</span> Loading note...</p>';
    try {
      const data = await API.getComments(q.qnum);
      const comments = data.comments || [];
      if (!comments.length) {
        commentsList.innerHTML = '<p class="text-muted text-sm">No note saved yet for this question.</p>';
        if (commentInput) commentInput.value = "";
        if (addCommentBtn) addCommentBtn.textContent = "Save Note";
        return;
      }

      const latest = comments[0];
      commentsList.innerHTML = `
        <div class="comment-item">
          <p class="comment-text">${escapeHtml(latest.comment_text)}</p>
          <div class="comment-meta">
            <span class="text-muted text-sm">Last updated ${formatDate(latest.created_at)}</span>
          </div>
        </div>
      `;
      if (commentInput) commentInput.value = latest.comment_text || "";
      if (addCommentBtn) addCommentBtn.textContent = "Update Note";
    } catch (err) {
      commentsList.innerHTML = '<p class="text-muted text-sm">Could not load note.</p>';
    }
  }

  async function saveComment() {
    if (!practiceState.userLoggedIn) {
      showToast("Sign in to save notes.", "warning");
      return;
    }
    const q = practiceState.lastQuestion;
    if (!q) return;

    const text = commentInput ? commentInput.value.trim() : "";
    if (!text) {
      showToast("Write a note first.", "warning");
      return;
    }

    try {
      await API.addComment(q.qnum || q.question_id, text);
      showToast("Note saved.", "success");
      await loadCommentsForCurrentQuestion();
    } catch (err) {
      showToast(`Failed to save note: ${err.message}`, "error");
    }
  }

  function renderQuestion(q) {
    if (!q) return;
    practiceState.lastQuestion = q;
    practiceState.chatHistory = [];
    renderChat();

    if (qTitle) qTitle.textContent = q.problem_name || "Untitled";
    if (qIndex) qIndex.textContent = `Question #${practiceState.currentIndex + 1}`;
    if (qDifficulty) qDifficulty.textContent = `Difficulty: ${q.difficulty || "Unknown"}`;
    if (qProblemUrl) {
      const url = q.problem_url || "#";
      qProblemUrl.href = url;
      qProblemUrl.textContent = url === "#" ? "No URL" : "Open Problem ↗";
    }

    const split = splitStatementExamples(q.statement_text || "");
    if (qStatement) qStatement.textContent = split.statement || "No statement available.";
    if (qConstraints) qConstraints.textContent = q.constraints_text || "No constraints available.";

    if (qExamples) {
      qExamples.innerHTML = "";
      let examples = parseArray(q.examples).map((e) => String(e).trim()).filter(Boolean);
      let blocks = examples.flatMap(splitExamples);
      if (!blocks.length && split.tail) blocks = splitExamples(split.tail);

      if (!blocks.length) {
        if (examplesArticle) examplesArticle.classList.add("hidden");
      } else {
        if (examplesArticle) examplesArticle.classList.remove("hidden");
        blocks.forEach((b) => {
          const pre = document.createElement("pre");
          pre.className = "example-block";
          pre.textContent = b;
          qExamples.appendChild(pre);
        });
      }
    }

    if (qTags) {
      qTags.innerHTML = "";
      const tags = [...parseArray(q.topic_tags), ...parseArray(q.company_tags)];
      if (!tags.length) {
        qTags.appendChild(createChip("No tags"));
      } else {
        [...new Set(tags)].forEach((t) => qTags.appendChild(createChip(t)));
      }
    }

    if (qRaw) qRaw.textContent = JSON.stringify(q.raw || q, null, 2);
    if (questionCard) questionCard.classList.remove("hidden");

    updateCounter();
    updateNavButtons();
    syncUrlWithQuestion(q);
    updateChatControls();
    loadCommentsForCurrentQuestion();
    syncOutcomeFromDatabase();
  }

  function goToIndex(index) {
    if (!practiceState.currentQuestions.length) return;
    if (index < 0 || index >= practiceState.currentQuestions.length) return;
    practiceState.currentIndex = index;
    renderQuestion(practiceState.currentQuestions[index]);
  }

  async function loadQuestions(targetQnum = null) {
    const company = companyInput ? companyInput.value.trim() : "";
    const difficulty = difficultySelect ? difficultySelect.value : "easy";
    if (!company) {
      setStatus("Enter a company name.");
      return;
    }

    setStatus("Loading questions...");
    try {
      const data = await API.getAllQuestions(company, difficulty);
      practiceState.currentQuestions = data.questions || [];
      practiceState.poolSize = practiceState.currentQuestions.length;

      if (!practiceState.currentQuestions.length) {
        setStatus(`No ${difficulty} questions for ${company}.`);
        if (questionCard) questionCard.classList.add("hidden");
        setQuestionControlsEnabled(false);
        updateCounter();
        return;
      }

      let startIndex = 0;
      if (targetQnum) {
        const idx = practiceState.currentQuestions.findIndex((q) => Number(q.qnum) === Number(targetQnum));
        if (idx >= 0) startIndex = idx;
      }

      practiceState.currentIndex = startIndex;
      setQuestionControlsEnabled(true);
      if (resetBtn) resetBtn.disabled = false;
      renderQuestion(practiceState.currentQuestions[startIndex]);
      setStatus(`Loaded ${practiceState.poolSize} ${difficulty} questions for ${company}.`);
    } catch (err) {
      setStatus(`Error: ${err.message}`);
    }
  }

  function goNext() {
    if (practiceState.currentIndex >= practiceState.currentQuestions.length - 1) {
      setStatus("You are on the last question.");
      return;
    }
    goToIndex(practiceState.currentIndex + 1);
  }

  function goPrev() {
    if (practiceState.currentIndex <= 0) {
      setStatus("You are on the first question.");
      return;
    }
    goToIndex(practiceState.currentIndex - 1);
  }

  function resetSequence() {
    if (!practiceState.currentQuestions.length) return;
    goToIndex(0);
    setStatus("Reset to the first question.");
  }

  async function markQuestion(outcome, statusLabel) {
    const q = practiceState.lastQuestion;
    if (!q) {
      setStatus("Load a question first.");
      return;
    }

    if (!practiceState.userLoggedIn) {
      showToast("Sign in to save progress.", "warning");
      return;
    }

    try {
      await API.updateProgress(q.qnum || q.question_id, {
        outcome: outcome,
        revisit: practiceState.progress.revisit,
      });
      showToast(`Marked as ${statusLabel}.`, "success");
      setStatus(`Saved as ${statusLabel}.`);
      applyOutcomeSelection({ outcome: outcome, revisit: practiceState.progress.revisit });
    } catch (err) {
      showToast(`Failed to save progress: ${err.message}`, "error");
      setStatus(`Error: ${err.message}`);
    }
  }

  async function toggleRevisitForQuestion() {
    const q = practiceState.lastQuestion;
    if (!q) {
      setStatus("Load a question first.");
      return;
    }

    if (!practiceState.userLoggedIn) {
      showToast("Sign in to save progress.", "warning");
      return;
    }

    const nextRevisit = !practiceState.progress.revisit;
    const outcome = practiceState.progress.outcome || "unsolved";

    try {
      await API.updateProgress(q.qnum || q.question_id, {
        outcome: outcome,
        revisit: nextRevisit,
      });
      applyOutcomeSelection({ outcome: outcome, revisit: nextRevisit });
      showToast(nextRevisit ? "Added to revisit queue." : "Removed from revisit queue.", "success");
      setStatus(nextRevisit ? "Saved to revisit queue." : "Removed from revisit queue.");
    } catch (err) {
      showToast(`Failed to update revisit state: ${err.message}`, "error");
      setStatus(`Error: ${err.message}`);
    }
  }

  async function clearQuestionProgress() {
    const q = practiceState.lastQuestion;
    if (!q) {
      setStatus("Load a question first.");
      return;
    }

    if (!practiceState.userLoggedIn) {
      showToast("Sign in to save progress.", "warning");
      return;
    }

    try {
      await API.clearProgress(q.qnum || 0);
      showToast("Marked as not solved.", "success");
      setStatus("Saved as not solved.");
      applyOutcomeSelection({ outcome: "unsolved", revisit: false });
    } catch (err) {
      showToast(`Failed to clear progress: ${err.message}`, "error");
      setStatus(`Error: ${err.message}`);
    }
  }

  function copyLink() {
    const q = practiceState.lastQuestion;
    if (!q || !q.problem_url) {
      setStatus("No link available.");
      return;
    }

    navigator.clipboard
      .writeText(q.problem_url)
      .then(() => {
        showToast("Problem link copied.", "success");
        setStatus("Link copied.");
      })
      .catch(() => setStatus("Could not copy link."));
  }

  function surpriseCompany() {
    if (!practiceState.companies.length || !companyInput) return;
    const idx = Math.floor(Math.random() * practiceState.companies.length);
    companyInput.value = practiceState.companies[idx];
    setStatus(`Surprise company: ${practiceState.companies[idx]}`);
  }

  function renderChat() {
    if (!chatMessages) return;
    chatMessages.innerHTML = "";
    if (!practiceState.chatHistory.length) {
      const p = document.createElement("p");
      p.className = "chat-empty";
      p.textContent = "Load a question, then ask your doubt here.";
      chatMessages.appendChild(p);
      return;
    }

    practiceState.chatHistory.forEach((item) => {
      const bubble = document.createElement("article");
      bubble.className = `chat-bubble ${item.role === "assistant" ? "assistant" : "user"}`;
      const role = document.createElement("p");
      role.className = "chat-role";
      role.textContent = item.role === "assistant" ? "Assistant" : "You";
      const body = document.createElement("p");
      body.className = "chat-text";
      body.textContent = item.role === "assistant" ? normalizeAssistantText(item.content) : item.content;
      bubble.appendChild(role);
      bubble.appendChild(body);
      chatMessages.appendChild(bubble);
    });
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  function showTypingIndicator() {
    if (!chatMessages) return;
    const typing = document.createElement("article");
    typing.className = "chat-bubble assistant typing-indicator";
    typing.id = "typingIndicator";
    typing.innerHTML = '<p class="chat-role">Assistant</p><p class="chat-text"><span class="typing-dots"><span>.</span><span>.</span><span>.</span></span> Thinking...</p>';
    chatMessages.appendChild(typing);
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  function removeTypingIndicator() {
    const el = document.getElementById("typingIndicator");
    if (el) el.remove();
  }

  function getCurrentQuestionText() {
    const q = practiceState.lastQuestion;
    if (!q) return "";
    return `Title: ${q.problem_name || ""}\n\nStatement:\n${q.statement_text || ""}\n\nConstraints:\n${q.constraints_text || ""}`.trim();
  }

  async function askAssistant() {
    if (practiceState.chatInFlight) return;
    const qText = getCurrentQuestionText();
    if (!qText) {
      setStatus("Load a question first.");
      return;
    }
    const doubt = doubtInput ? doubtInput.value.trim() : "";
    if (!doubt) {
      setStatus("Type your doubt first.");
      return;
    }

    practiceState.chatHistory.push({ role: "user", content: doubt });
    if (doubtInput) doubtInput.value = "";
    renderChat();
    practiceState.chatInFlight = true;
    updateChatControls();
    showTypingIndicator();

    try {
      const data = await API.askAssistant(qText, doubt, practiceState.chatHistory.slice(-12));
      removeTypingIndicator();
      practiceState.chatHistory.push({ role: "assistant", content: (data.answer || "No answer returned.").trim() });
      renderChat();
      setStatus("Assistant responded.");
    } catch (err) {
      removeTypingIndicator();
      practiceState.chatHistory.push({ role: "assistant", content: `Error: ${err.message}` });
      renderChat();
      setStatus(`Assistant error: ${err.message}`);
    } finally {
      practiceState.chatInFlight = false;
      updateChatControls();
    }
  }

  async function guarded(fn) {
    if (practiceState.isBusy) return;
    practiceState.isBusy = true;
    try {
      await fn();
    } finally {
      setTimeout(() => {
        practiceState.isBusy = false;
      }, 150);
    }
  }

  try {
    const data = await API.getCompanies();
    practiceState.companies = data.companies || [];
    if (companyOptions) {
      companyOptions.innerHTML = "";
      practiceState.companies.forEach((name) => {
        const opt = document.createElement("option");
        opt.value = name;
        companyOptions.appendChild(opt);
      });
    }
    if (companyInput && practiceState.companies.length && !companyInput.value) {
      companyInput.value = practiceState.companies[0];
    }
    setStatus(`${practiceState.companies.length} companies loaded.`);
  } catch (err) {
    setStatus(`Error loading companies: ${err.message}`);
  }

  const params = new URLSearchParams(window.location.search);
  const presetCompany = params.get("company");
  const presetDifficulty = params.get("difficulty");
  const presetQnum = Number(params.get("qnum") || 0);

  if (presetCompany && companyInput) companyInput.value = presetCompany;
  if (presetDifficulty && difficultySelect) difficultySelect.value = String(presetDifficulty).toLowerCase();

  if (startBtn) startBtn.addEventListener("click", () => guarded(() => loadQuestions()));
  if (prevBtn) prevBtn.addEventListener("click", () => guarded(goPrev));
  if (nextBtn) nextBtn.addEventListener("click", () => guarded(goNext));
  if (recommendBtn) recommendBtn.addEventListener("click", () => guarded(goNext));
  if (resetBtn) resetBtn.addEventListener("click", () => guarded(resetSequence));
  if (surpriseBtn) surpriseBtn.addEventListener("click", () => guarded(surpriseCompany));
  if (copyBtn) copyBtn.addEventListener("click", () => guarded(copyLink));

  if (markSolvedBtn) markSolvedBtn.addEventListener("click", () => guarded(() => markQuestion("solved", "Solved")));
  if (markUnsolvedBtn) markUnsolvedBtn.addEventListener("click", () => guarded(clearQuestionProgress));
  if (markRevisitBtn) markRevisitBtn.addEventListener("click", () => guarded(toggleRevisitForQuestion));

  if (addCommentBtn) addCommentBtn.addEventListener("click", () => guarded(saveComment));

  if (sendDoubtBtn) sendDoubtBtn.addEventListener("click", () => guarded(askAssistant));
  if (clearChatBtn) {
    clearChatBtn.addEventListener("click", () => {
      practiceState.chatHistory = [];
      renderChat();
      setStatus("Chat cleared.");
    });
  }

  if (doubtInput) {
    doubtInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        guarded(askAssistant);
      }
    });
  }

  document.addEventListener("keydown", (e) => {
    if (["INPUT", "TEXTAREA", "SELECT"].includes(e.target.tagName)) return;
    const k = e.key.toLowerCase();
    if (k === "n" && nextBtn && !nextBtn.disabled) guarded(goNext);
    if (k === "p" && prevBtn && !prevBtn.disabled) guarded(goPrev);
    if (k === "l") guarded(() => loadQuestions());
  });

  renderChat();
  updateChatControls();
  updateCounter();
  setQuestionControlsEnabled(false);

  if (presetCompany && presetDifficulty) {
    await loadQuestions(presetQnum > 0 ? presetQnum : null);
  }
}
