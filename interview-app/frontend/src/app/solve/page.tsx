"use client";

import React, { useState, useEffect, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { API } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { AssistantChat } from "@/components/AssistantChat";
import { Spinner } from "@/components/Spinner";
import { Brain, CheckCircle, XCircle, Undo2, RotateCcw, MessageSquare, ExternalLink, ArrowLeft } from "lucide-react";
import Link from "next/link";

function splitStatementExamples(text: string) {
  const s = String(text || "").replace(/\r\n?/g, "\n");
  const m = s.match(/\n?\s*Examples?\s*:/i);
  if (!m || typeof m.index !== "number") return { statement: s.trim(), tail: "" };
  return { statement: s.slice(0, m.index).trim(), tail: s.slice(m.index).trim() };
}

function splitExamples(rawText: string) {
  const text = String(rawText || "").replace(/\r\n?/g, "\n").trim();
  if (!text) return [];
  const byHeading = text.split(/(?=\bExample\s*\d+\s*:)/i).map((s) => s.trim()).filter(Boolean);
  if (byHeading.length > 1) return byHeading;
  const byInput = text.split(/(?=\bInput\s*:)/i).map((s) => s.trim()).filter(Boolean);
  if (byInput.length > 1) return byInput;
  return [text];
}

function parseArray(v: any) {
  return Array.isArray(v) ? v : v ? [String(v)] : [];
}

function formatDate(dateStr: string) {
  if (!dateStr) return "";
  try {
    return new Date(dateStr).toLocaleDateString();
  } catch (_) {
    return dateStr;
  }
}

function SolveContent() {
  const { user } = useAuth();
  const searchParams = useSearchParams();
  const qnumParam = Number(searchParams.get("qnum") || 0);

  const [currentQ, setCurrentQ] = useState<any>(null);
  const [statusText, setStatusText] = useState("Loading question...");
  const [isBusy, setIsBusy] = useState(false);

  const [progress, setProgress] = useState<{ is_solved: boolean | null; revisit: boolean }>({ is_solved: null, revisit: false });
  const [commentText, setCommentText] = useState("");
  const [commentMeta, setCommentMeta] = useState("");
  const [commentId, setCommentId] = useState<string | null>(null);
  
  const [toastMsg, setToastMsg] = useState("");
  const [toastType, setToastType] = useState("info");
  const [showToast, setShowToast] = useState(false);

  const displayToast = (msg: string, type = "info") => {
    setToastMsg(msg);
    setToastType(type);
    setShowToast(true);
    setTimeout(() => setShowToast(false), 2600);
  };

  const loadNote = async (qnum: number) => {
    if (!user) {
      setCommentMeta("Sign in to view and save note.");
      return;
    }
    setCommentMeta("Loading note...");
    try {
      const data = await API.getComments(String(qnum));
      const comments = data.comments || [];
      if (!comments.length) {
        setCommentMeta("No comment is found.");
        setCommentText("");
        setCommentId(null);
        return;
      }
      const latest = comments[0];
      setCommentText(latest.comment_text || "");
      setCommentMeta(`Last updated ${formatDate(latest.created_at)}`);
      setCommentId(latest.id || null);
    } catch (err) {
      setCommentMeta("Could not load note.");
    }
  };

  useEffect(() => {
    let mounted = true;
    if (qnumParam <= 0) {
      setStatusText("Invalid question. Please open a question from All Questions page.");
      return;
    }

    setStatusText("Loading question...");
    API.getQuestionByQnum(String(qnumParam)).then(q => {
      if (!mounted) return;
      setCurrentQ(q);
      setStatusText("Question loaded.");
      
      if (user) {
        API.getProgressStatus(String(q.qnum)).then(data => {
          if (!mounted) return;
          const hasIsSolved = Object.prototype.hasOwnProperty.call(data || {}, "is_solved");
          const isSolved = hasIsSolved ? (data?.is_solved === null ? null : Boolean(data?.is_solved)) : null;
          const revisit = Boolean(data?.revisit);
          setProgress({ is_solved: isSolved, revisit });
        }).catch(() => {
          if (mounted) setProgress({ is_solved: null, revisit: false });
        });
      }
      
      loadNote(q.qnum);
    }).catch(err => {
      if (mounted) setStatusText(`Could not load question: ${err.message}`);
    });

    return () => { mounted = false; };
  }, [qnumParam, user]);

  const markQuestion = async (isSolved: boolean | null) => {
    if (!currentQ) return;
    if (progress.is_solved === isSolved) return; // Prevent duplicate API call
    if (!user) return displayToast("Sign in to save progress.", "warning");
    setIsBusy(true);
    try {
      if (isSolved === null) {
        await API.clearProgress(currentQ.qnum);
        setProgress(p => ({ ...p, is_solved: null }));
        displayToast("Marked as not solved.", "success");
        setStatusText("Saved as not solved.");
      } else {
        await API.updateProgress(currentQ.qnum, { is_solved: isSolved, revisit: progress.revisit });
        setProgress(p => ({ ...p, is_solved: isSolved }));
        const label = isSolved ? "Solved" : "Not Solved";
        displayToast(`Marked as ${label}.`, "success");
        setStatusText(`Saved as ${label}.`);
      }
    } catch (err: any) {
      displayToast(`Failed to save progress: ${err.message}`, "error");
      setStatusText(`Error: ${err.message}`);
    } finally {
      setIsBusy(false);
    }
  };

  const markUnsolved = async () => {
    if (!currentQ) return;
    if (progress.is_solved === false) return; // Prevent duplicate API call
    if (!user) return displayToast("Sign in to save progress.", "warning");
    setIsBusy(true);
    try {
      await API.updateProgress(currentQ.qnum, { is_solved: false, revisit: progress.revisit });
      setProgress(p => ({ ...p, is_solved: false }));
      displayToast("Marked as not solved.", "success");
      setStatusText("Saved as not solved.");
    } catch (err: any) {
      displayToast(`Failed to clear progress: ${err.message}`, "error");
    } finally {
      setIsBusy(false);
    }
  };

  const toggleRevisit = async () => {
    if (!currentQ) return;
    if (!user) return displayToast("Sign in to save progress.", "warning");
    const nextRevisit = !progress.revisit;
    setIsBusy(true);
    try {
      await API.updateProgress(currentQ.qnum, { is_solved: progress.is_solved ?? false, revisit: nextRevisit });
      setProgress(p => ({ ...p, revisit: nextRevisit }));
      displayToast(nextRevisit ? "Added to revisit queue." : "Removed from revisit queue.", "success");
      setStatusText(nextRevisit ? "Saved to revisit queue." : "Removed from revisit queue.");
    } catch (err: any) {
      displayToast(`Failed to update revisit state: ${err.message}`, "error");
    } finally {
      setIsBusy(false);
    }
  };

  const saveNote = async () => {
    if (!user) return displayToast("Sign in to save note.", "warning");
    if (!currentQ) return;
    const text = commentText.trim();
    if (!text) return displayToast("Write your note first.", "warning");
    
    setIsBusy(true);
    try {
      await API.addComment(currentQ.qnum, text);
      displayToast("Note saved.", "success");
      await loadNote(currentQ.qnum);
    } catch (err: any) {
      displayToast(`Failed to save: ${err.message}`, "error");
    } finally {
      setIsBusy(false);
    }
  };

  const deleteNote = async () => {
    if (!commentId) return displayToast("No comment to delete.", "warning");
    if (!user) return displayToast("Sign in to delete comment.", "warning");
    setIsBusy(true);
    try {
      await API.deleteComment(commentId);
      setCommentText("");
      displayToast("Comment deleted.", "success");
      await loadNote(currentQ.qnum);
    } catch (err: any) {
      displayToast(`Failed to delete: ${err.message}`, "error");
    } finally {
      setIsBusy(false);
    }
  };

  let statementText = "No statement available.";
  let constraintText = "No constraints available.";
  let examplesBlocks: string[] = [];
  let tags: string[] = [];
  let currentQTextForAssistant = "";
  
  if (currentQ) {
    const split = splitStatementExamples(currentQ.statement_text);
    statementText = split.statement || "No statement available.";
    constraintText = currentQ.constraints_text || "No constraints available.";
    
    const ex = parseArray(currentQ.examples).map(e => String(e).trim()).filter(Boolean);
    examplesBlocks = ex.flatMap(splitExamples);
    if (!examplesBlocks.length && split.tail) examplesBlocks = splitExamples(split.tail);
    
    tags = Array.from(new Set([...parseArray(currentQ.topic_tags), ...parseArray(currentQ.company_tags)]));
    currentQTextForAssistant = `Title: ${currentQ.problem_name || ""}\n\nStatement:\n${statementText}\n\nConstraints:\n${constraintText}`;
  }

  return (
    <main className="main-content">
      {showToast && (
        <div id="toast" className={`toast toast-${toastType} toast-show`}>
          {toastMsg}
        </div>
      )}
      
      <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h1 style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <Brain size={28} className="text-teal" /> Solve Question
        </h1>
        <Link href="/questions" className="btn btn-sm"><ArrowLeft size={16} /> Back To All Questions</Link>
      </div>

      <div className="status-bar section" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '1.5rem', marginBottom: '1.5rem', fontSize: '0.9rem', color: 'var(--muted)' }}>
        <span className="status-text">{statusText}</span>
        <div className="status-right">
          <span className="counter-badge" style={{ background: 'var(--sidebar-hover)', padding: '0.2rem 0.5rem', borderRadius: '1rem', color: 'var(--ink)' }}>#{qnumParam || 0}</span>
        </div>
      </div>

      {currentQ && (
        <section className="question-card section" aria-live="polite" style={{ background: 'var(--paper)', borderRadius: 'var(--radius-lg)', border: '1px solid var(--line)', padding: '2rem', display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
          <div className="question-head" style={{ borderBottom: '1px solid var(--line)', paddingBottom: '1rem' }}>
            <h2 style={{ fontSize: '1.5rem', marginBottom: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              {currentQ.problem_name || "Untitled"}
            </h2>
            <div className="pill-row" style={{ display: 'flex', gap: '0.5rem' }}>
              <span className="pill" style={{ background: 'var(--sidebar-hover)', padding: '0.2rem 0.6rem', borderRadius: '1rem', fontSize: '0.85rem' }}>{currentQ.difficulty || "Unknown"}</span>
            </div>
          </div>

          <div className="quick-links">
            <a href={currentQ.problem_url || "#"} target="_blank" rel="noopener noreferrer" style={{ display: 'inline-flex', alignItems: 'center', gap: '0.4rem', color: 'var(--teal)', textDecoration: 'none', fontWeight: 500 }}>
              {currentQ.problem_url ? <><ExternalLink size={16} /> Open Problem</> : "No URL"}
            </a>
          </div>

          <div className="details-grid" style={{ display: 'grid', gap: '1.5rem' }}>
            <article>
              <h3 style={{ fontSize: '1.1rem', marginBottom: '0.75rem', color: 'var(--ink)' }}>Statement</h3>
              <pre className="text-block" style={{ whiteSpace: 'pre-wrap', wordWrap: 'break-word', fontFamily: 'inherit', color: 'var(--muted)', background: 'var(--bg)', padding: '1rem', borderRadius: 'var(--radius)', border: '1px solid var(--line)' }}>{statementText}</pre>
            </article>
            
            {examplesBlocks.length > 0 && (
              <article>
                <h3 style={{ fontSize: '1.1rem', marginBottom: '0.75rem', color: 'var(--ink)' }}>Examples</h3>
                <div className="chip-list" style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                  {examplesBlocks.map((b, i) => (
                    <pre key={i} className="example-block" style={{ whiteSpace: 'pre-wrap', fontFamily: 'var(--font-mono)', fontSize: '0.9rem', background: 'var(--sidebar-bg)', padding: '1rem', borderRadius: 'var(--radius)', border: '1px solid var(--line)', color: 'var(--ink)' }}>{b}</pre>
                  ))}
                </div>
              </article>
            )}

            <article>
              <h3 style={{ fontSize: '1.1rem', marginBottom: '0.75rem', color: 'var(--ink)' }}>Tags</h3>
              <details className="inline-dropdown" style={{ background: 'var(--bg)', border: '1px solid var(--line)', borderRadius: 'var(--radius)', padding: '0.5rem 1rem' }}>
                <summary style={{ cursor: 'pointer', fontWeight: 500 }}>Show Tags</summary>
                <div className="chip-list" style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', marginTop: '1rem' }}>
                  {tags.length ? tags.map(t => (
                    <span key={t} className="chip" style={{ background: 'var(--sidebar-hover)', padding: '0.25rem 0.75rem', borderRadius: '1rem', fontSize: '0.85rem' }}>{t}</span>
                  )) : (
                    <span className="chip" style={{ background: 'var(--sidebar-hover)', padding: '0.25rem 0.75rem', borderRadius: '1rem', fontSize: '0.85rem' }}>No tags</span>
                  )}
                </div>
              </details>
            </article>

            <article>
              <h3 style={{ fontSize: '1.1rem', marginBottom: '0.75rem', color: 'var(--ink)' }}>Constraints</h3>
              <pre className="text-block" style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit', color: 'var(--muted)', background: 'var(--bg)', padding: '1rem', borderRadius: 'var(--radius)', border: '1px solid var(--line)' }}>{constraintText}</pre>
            </article>
          </div>
        </section>
      )}

      {currentQ && (
        <section className="card-flat section" style={{ padding: '1.5rem', background: 'var(--paper)', borderRadius: 'var(--radius-lg)', border: '1px solid var(--line)', marginTop: '2rem' }}>
          <div className="card-header" style={{ marginBottom: '0.5rem' }}>
            <h3 style={{ fontSize: '1.1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <CheckCircle size={18} className="text-teal" /> Question Outcome
            </h3>
          </div>
          <p className="card-subtitle text-muted" style={{ marginBottom: '1rem', fontSize: '0.9rem' }}>Set this manually. Opening a question does not mark it as solved.</p>
          <div className="button-row" style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
            <button 
              className={`btn btn-sm outcome-btn ${progress.is_solved === true ? "btn-feedback-selected" : ""}`} 
              type="button" 
              onClick={() => markQuestion(true)} 
              disabled={isBusy}
              style={{ background: progress.is_solved === true ? 'var(--teal-soft)' : 'var(--bg)', color: progress.is_solved === true ? 'var(--teal)' : 'var(--ink)', borderColor: progress.is_solved === true ? 'var(--teal)' : 'var(--line)' }}
            >
              <CheckCircle size={16} /> Solved
            </button>
            <button 
              className={`btn btn-sm outcome-btn ${progress.is_solved === false ? "btn-feedback-selected" : ""}`} 
              type="button" 
              onClick={markUnsolved} 
              disabled={isBusy}
              style={{ background: progress.is_solved === false ? 'var(--red)' : 'var(--bg)', color: progress.is_solved === false ? 'white' : 'var(--ink)', borderColor: progress.is_solved === false ? 'var(--red)' : 'var(--line)' }}
            >
              <XCircle size={16} /> Not Solved
            </button>
            <button 
              className={`btn btn-sm outcome-btn ${progress.revisit ? "btn-feedback-selected" : ""}`} 
              type="button" 
              onClick={toggleRevisit} 
              disabled={isBusy}
              style={{ background: progress.revisit ? 'var(--amber)' : 'var(--bg)', color: progress.revisit ? 'black' : 'var(--ink)', borderColor: progress.revisit ? 'var(--amber)' : 'var(--line)' }}
            >
              {progress.revisit ? <><Undo2 size={16} /> Remove From Revisit</> : <><RotateCcw size={16} /> Add To Revisit</>}
            </button>
          </div>
        </section>
      )}

      {currentQ && (
        <section className="card-flat section" style={{ padding: '1.5rem', background: 'var(--paper)', borderRadius: 'var(--radius-lg)', border: '1px solid var(--line)', marginTop: '2rem' }}>
          <div className="card-header" style={{ marginBottom: '0.5rem' }}>
            <h3 style={{ fontSize: '1.1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <MessageSquare size={18} className="text-teal" /> Your Note
            </h3>
          </div>
          <p className="card-subtitle text-muted" style={{ marginBottom: '1rem', fontSize: '0.9rem' }}>Your previous note is loaded automatically. Save again to overwrite.</p>
          <div className="comments-list" style={{ marginBottom: '1rem' }}>
            <div className="comment-item" style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              {commentMeta && (
                <div className="comment-meta" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
                  <span className="text-muted text-sm">{commentMeta}</span>
                  {commentId && (
                    <button type="button" className="btn btn-sm comment-delete-btn" style={{ background: 'transparent', border: '1px solid var(--red)', color: 'var(--red)', padding: '0.2rem 0.6rem' }} onClick={deleteNote} disabled={isBusy}>Delete Note</button>
                  )}
                </div>
              )}
            </div>
          </div>
          <div className="comment-input-wrap" style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            <textarea 
              value={commentText}
              onChange={e => setCommentText(e.target.value)}
              placeholder="Write your note for this question..." 
              rows={3}
              style={{ width: '100%', padding: '0.75rem', borderRadius: 'var(--radius)', border: '1px solid var(--line)', background: 'var(--bg)', color: 'var(--ink)', resize: 'vertical' }}
            />
            <button className="btn btn-primary btn-sm" style={{ alignSelf: 'flex-start' }} type="button" onClick={saveNote} disabled={isBusy}>
              {commentId ? "Update Note" : "Save Note"}
            </button>
          </div>
        </section>
      )}

      {currentQ && (
        <div style={{ marginTop: '2rem', marginBottom: '2rem' }}>
          <AssistantChat questionText={currentQTextForAssistant} />
        </div>
      )}
    </main>
  );
}

export default function SolvePage() {
  return (
    <Suspense fallback={<Spinner text="Loading..." />}>
      <SolveContent />
    </Suspense>
  );
}
