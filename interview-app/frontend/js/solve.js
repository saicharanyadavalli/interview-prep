/**
 * solve.js — Single question solving page.
 */

const solveState = {
  question: null,
  userLoggedIn: false,
  chatHistory: [],
  chatInFlight: false,
  progress: { outcome: null, revisit: false },
};

document.addEventListener("DOMContentLoaded", async () => {
  const user = await initSidebar("questions", { requireLogin: true });
  if (!user) {
    return;
  }
  solveState.userLoggedIn = Boolean(user);

  if (user) {
    const { session } = await getSession();
    if (session) await syncSessionWithBackend(session.access_token);
  }

  initSolvePage();
});

async function initSolvePage() {
  const statusText = document.getElementById("statusText");
  const qnumBadge = document.getElementById("qnumBadge");
  const qTitle = document.getElementById("qTitle");
  const qCompany = document.getElementById("qCompany");
  const qDifficulty = document.getElementById("qDifficulty");
  const qProblemUrl = document.getElementById("qProblemUrl");
  const qStatement = document.getElementById("qStatement");
  const examplesArticle = document.getElementById("examplesArticle");
  const qExamples = document.getElementById("qExamples");
  const qTags = document.getElementById("qTags");
  const qConstraints = document.getElementById("qConstraints");

  const commentsList = document.getElementById("commentsList");
  const commentInput = document.getElementById("commentInput");
  const saveCommentBtn = document.getElementById("saveCommentBtn");
  const markSolvedBtn = document.getElementById("markSolvedBtn");
  const markUnsolvedBtn = document.getElementById("markUnsolvedBtn");
  const markRevisitBtn = document.getElementById("markRevisitBtn");

  const chatMessages = document.getElementById("chatMessages");
  const doubtInput = document.getElementById("doubtInput");
  const sendDoubtBtn = document.getElementById("sendDoubtBtn");
  const clearChatBtn = document.getElementById("clearChatBtn");

  function setStatus(msg) {
    if (statusText) statusText.textContent = msg;
  }

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

  function parseArray(v) {
    return Array.isArray(v) ? v : v ? [String(v)] : [];
  }

  function createChip(text) {
    const span = document.createElement("span");
    span.className = "chip";
    span.textContent = text;
    return span;
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

  function splitStatementExamples(text) {
    const s = String(text || "").replace(/\r\n?/g, "\n");
    const m = s.match(/\n?\s*Examples?\s*:/i);
    if (!m || typeof m.index !== "number") return { statement: s.trim(), tail: "" };
    return { statement: s.slice(0, m.index).trim(), tail: s.slice(m.index).trim() };
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

  function renderQuestion(q) {
    if (!q) return;
    solveState.question = q;

    if (qnumBadge) qnumBadge.textContent = `#${q.qnum || 0}`;
    if (qTitle) qTitle.textContent = q.problem_name || "Untitled";
    if (qCompany) qCompany.textContent = q.company || "Unknown Company";
    if (qDifficulty) qDifficulty.textContent = q.difficulty || "Unknown";
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
      let blocks = parseArray(q.examples).flatMap(splitExamples);
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

    syncOutcomeFromDatabase();
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
    solveState.progress = state;

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
    const q = solveState.question;
    if (!q || !solveState.userLoggedIn) return;

    try {
      const data = await API.getProgressStatus(q.qnum);
      applyOutcomeSelection(data || null);
    } catch (_) {
      // Keep neutral state on lookup failure.
    }
  }

  async function loadNote() {
    const q = solveState.question;
    if (!q || !commentsList) return;

    if (!solveState.userLoggedIn) {
      commentsList.innerHTML = '<p class="text-muted text-sm">Sign in to view and save note.</p>';
      if (commentInput) commentInput.value = "";
      return;
    }

    commentsList.innerHTML = '<p class="loading"><span class="loading-dot">⏳</span> Loading note...</p>';
    try {
      const data = await API.getComments(q.qnum);
      const comments = data.comments || [];
      if (!comments.length) {
        commentsList.innerHTML = '<p class="text-muted text-sm">No note yet.</p>';
        if (commentInput) commentInput.value = "";
        if (saveCommentBtn) saveCommentBtn.textContent = "Save Note";
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
      if (saveCommentBtn) saveCommentBtn.textContent = "Update Note";
    } catch (err) {
      commentsList.innerHTML = '<p class="text-muted text-sm">Could not load note.</p>';
    }
  }

  async function saveNote() {
    const q = solveState.question;
    if (!q) return;

    if (!solveState.userLoggedIn) {
      showToast("Sign in to save note.", "warning");
      return;
    }

    const text = commentInput ? commentInput.value.trim() : "";
    if (!text) {
      showToast("Write your note first.", "warning");
      return;
    }

    try {
      await API.addComment(q.qnum, text);
      await loadNote();
      showToast("Note saved.", "success");
    } catch (err) {
      showToast(`Failed to save: ${err.message}`, "error");
    }
  }

  async function markStatus(outcome, statusLabel) {
    const q = solveState.question;
    if (!q) return;

    if (!solveState.userLoggedIn) {
      showToast("Sign in to save progress.", "warning");
      return;
    }

    try {
      await API.updateProgress(q.qnum, {
        outcome: outcome,
        revisit: solveState.progress.revisit,
      });
      showToast(`Marked as ${statusLabel}.`, "success");
      setStatus(`Saved as ${statusLabel}.`);
      applyOutcomeSelection({ outcome: outcome, revisit: solveState.progress.revisit });
    } catch (err) {
      showToast(`Failed to save progress: ${err.message}`, "error");
    }
  }

  async function toggleRevisit() {
    const q = solveState.question;
    if (!q) return;

    if (!solveState.userLoggedIn) {
      showToast("Sign in to save progress.", "warning");
      return;
    }

    const nextRevisit = !solveState.progress.revisit;
    const outcome = solveState.progress.outcome || "unsolved";

    try {
      await API.updateProgress(q.qnum, {
        outcome: outcome,
        revisit: nextRevisit,
      });
      applyOutcomeSelection({ outcome: outcome, revisit: nextRevisit });
      showToast(nextRevisit ? "Added to revisit queue." : "Removed from revisit queue.", "success");
      setStatus(nextRevisit ? "Saved to revisit queue." : "Removed from revisit queue.");
    } catch (err) {
      showToast(`Failed to update revisit state: ${err.message}`, "error");
    }
  }

  async function clearProgress() {
    const q = solveState.question;
    if (!q) return;

    if (!solveState.userLoggedIn) {
      showToast("Sign in to save progress.", "warning");
      return;
    }

    try {
      await API.updateProgress(q.qnum, {
        outcome: "unsolved",
        revisit: false,
      });
      showToast("Marked as not solved.", "success");
      setStatus("Saved as not solved.");
      applyOutcomeSelection({ outcome: "unsolved", revisit: false });
    } catch (err) {
      showToast(`Failed to clear progress: ${err.message}`, "error");
    }
  }

  function getCurrentQuestionText() {
    const q = solveState.question;
    if (!q) return "";
    return `Title: ${q.problem_name || ""}\n\nStatement:\n${q.statement_text || ""}\n\nConstraints:\n${q.constraints_text || ""}`.trim();
  }

  function renderChat() {
    if (!chatMessages) return;
    chatMessages.innerHTML = "";
    if (!solveState.chatHistory.length) {
      const p = document.createElement("p");
      p.className = "chat-empty";
      p.textContent = "Ask anything related to this question.";
      chatMessages.appendChild(p);
      return;
    }

    solveState.chatHistory.forEach((item) => {
      const bubble = document.createElement("article");
      bubble.className = `chat-bubble ${item.role === "assistant" ? "assistant" : "user"}`;
      const role = document.createElement("p");
      role.className = "chat-role";
      role.textContent = item.role === "assistant" ? "Assistant" : "You";
      const body = document.createElement("p");
      body.className = "chat-text";
      body.textContent = item.content;
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

  async function askAssistant() {
    if (solveState.chatInFlight) return;
    const qText = getCurrentQuestionText();
    if (!qText) return;

    const doubt = doubtInput ? doubtInput.value.trim() : "";
    if (!doubt) {
      setStatus("Type a doubt first.");
      return;
    }

    solveState.chatHistory.push({ role: "user", content: doubt });
    if (doubtInput) doubtInput.value = "";
    renderChat();

    solveState.chatInFlight = true;
    showTypingIndicator();

    try {
      const data = await API.askAssistant(qText, doubt, solveState.chatHistory.slice(-12));
      removeTypingIndicator();
      solveState.chatHistory.push({ role: "assistant", content: data.answer || "No answer returned." });
      renderChat();
      setStatus("Assistant responded.");
    } catch (err) {
      removeTypingIndicator();
      solveState.chatHistory.push({ role: "assistant", content: `Error: ${err.message}` });
      renderChat();
      setStatus(`Assistant error: ${err.message}`);
    } finally {
      solveState.chatInFlight = false;
    }
  }

  const params = new URLSearchParams(window.location.search);
  const qnum = Number(params.get("qnum") || 0);

  if (qnum <= 0) {
    setStatus("Invalid question. Please open a question from All Questions page.");
    return;
  }

  try {
    setStatus("Loading question...");
    const q = await API.getQuestionByQnum(qnum);
    renderQuestion(q);
    setStatus("Question loaded.");
    await loadNote();
  } catch (err) {
    setStatus(`Could not load question: ${err.message}`);
  }

  if (saveCommentBtn) saveCommentBtn.addEventListener("click", saveNote);
  if (markSolvedBtn) markSolvedBtn.addEventListener("click", () => markStatus("solved", "Solved"));
  if (markUnsolvedBtn) markUnsolvedBtn.addEventListener("click", clearProgress);
  if (markRevisitBtn) markRevisitBtn.addEventListener("click", toggleRevisit);
  if (sendDoubtBtn) sendDoubtBtn.addEventListener("click", askAssistant);
  if (clearChatBtn) {
    clearChatBtn.addEventListener("click", () => {
      solveState.chatHistory = [];
      renderChat();
      setStatus("Chat cleared.");
    });
  }

  if (doubtInput) {
    doubtInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        askAssistant();
      }
    });
  }

  renderChat();
}
