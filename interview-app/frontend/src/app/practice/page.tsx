"use client";

import React, { useState, useEffect, useCallback, Suspense, useRef } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { API } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { AssistantChat } from "@/components/AssistantChat";
import { Spinner } from "@/components/Spinner";
import { Target, Lightbulb, RotateCcw, Dices, Copy, CheckCircle, XCircle, Undo2, MessageSquare, ExternalLink } from "lucide-react";
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

function PracticeContent() {
  const { user } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();

  const presetCompany = searchParams.get("company");
  const presetDifficulty = searchParams.get("difficulty");
  const presetQnum = Number(searchParams.get("qnum") || 0);

  const [companies, setCompanies] = useState<string[]>([]);
  const [companyInput, setCompanyInput] = useState(presetCompany || "");
  const [difficultySelect, setDifficultySelect] = useState(presetDifficulty || "easy");

  const [questions, setQuestions] = useState<any[]>([]);
  const [currentIndex, setCurrentIndex] = useState(-1);
  const poolSize = questions.length;
  const currentQ = currentIndex >= 0 && currentIndex < poolSize ? questions[currentIndex] : null;

  const [statusText, setStatusText] = useState("Choose company and difficulty to begin.");
  const [isBusy, setIsBusy] = useState(false);

  const [progress, setProgress] = useState<{ is_solved: boolean | null; revisit: boolean }>({ is_solved: null, revisit: false });
  const [commentText, setCommentText] = useState("");
  const [commentMeta, setCommentMeta] = useState("");
  
  const [toastMsg, setToastMsg] = useState("");
  const [toastType, setToastType] = useState("info");
  const [showToast, setShowToast] = useState(false);

  const displayToast = (msg: string, type = "info") => {
    setToastMsg(msg);
    setToastType(type);
    setShowToast(true);
    setTimeout(() => setShowToast(false), 2600);
  };

  const syncUrl = useCallback((q: any, comp: string, diff: string) => {
    if (!q) return;
    const params = new URLSearchParams();
    if (comp) params.set("company", comp);
    if (diff) params.set("difficulty", diff);
    if (q.qnum) params.set("qnum", String(q.qnum));
    router.replace(`?${params.toString()}`);
  }, [router]);

  // Load Companies on mount
  useEffect(() => {
    let mounted = true;
    API.getCompanies().then(data => {
      if (!mounted) return;
      const comps = data.companies || [];
      setCompanies(comps);
      if (comps.length > 0 && !companyInput && !presetCompany) {
        setCompanyInput(comps[0]);
      }
      setStatusText(`${comps.length} companies loaded.`);
    }).catch(err => {
      if (mounted) setStatusText(`Error loading companies: ${err.message}`);
    });
    return () => { mounted = false; };
  }, [presetCompany, companyInput]);

  // Sync Progress and Comments when question changes
  useEffect(() => {
    let mounted = true;
    if (!currentQ) return;
    
    syncUrl(currentQ, companyInput, difficultySelect);

    if (user) {
      API.getProgressStatus(currentQ.qnum).then(data => {
        if (!mounted) return;
        const hasIsSolved = Object.prototype.hasOwnProperty.call(data || {}, "is_solved");
        const isSolved = hasIsSolved ? (data?.is_solved === null ? null : Boolean(data?.is_solved)) : null;
        const revisit = Boolean(data?.revisit);
        setProgress({ is_solved: isSolved, revisit });
      }).catch(() => {
        if (mounted) setProgress({ is_solved: null, revisit: false });
      });

      API.getComments(currentQ.qnum).then(data => {
        if (!mounted) return;
        const comments = data.comments || [];
        if (comments.length > 0) {
          const latest = comments[0];
          setCommentText(latest.comment_text || "");
          setCommentMeta(`Last updated ${formatDate(latest.created_at)}`);
        } else {
          setCommentText("");
          setCommentMeta("");
        }
      }).catch(() => {
        if (mounted) setCommentMeta("Could not load note.");
      });
    } else {
      setProgress({ is_solved: null, revisit: false });
      setCommentText("");
      setCommentMeta("Sign in to sync notes.");
    }

    return () => { mounted = false; };
  }, [currentQ, user, companyInput, difficultySelect, syncUrl]);

  // Auto-load if presets exist
  useEffect(() => {
    if (presetCompany && presetDifficulty) {
      loadQuestions(presetCompany, presetDifficulty, presetQnum > 0 ? presetQnum : null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // Only once on mount

  const loadQuestions = async (comp = companyInput, diff = difficultySelect, targetQnum: number | null = null) => {
    const trimmedComp = comp.trim();
    if (!trimmedComp) {
      setStatusText("Enter a company name.");
      return;
    }

    setStatusText("Loading questions...");
    setIsBusy(true);
    try {
      const data = await API.getAllQuestions(trimmedComp, diff);
      const qs = data.questions || [];
      setQuestions(qs);
      
      if (!qs.length) {
        setStatusText(`No ${diff} questions for ${trimmedComp}.`);
        setCurrentIndex(-1);
      } else {
        let startIndex = 0;
        if (targetQnum) {
          const idx = qs.findIndex((q: any) => Number(q.qnum) === Number(targetQnum));
          if (idx >= 0) startIndex = idx;
        }
        setCurrentIndex(startIndex);
        setStatusText(`Loaded ${qs.length} ${diff} questions for ${trimmedComp}.`);
      }
    } catch (err: any) {
      setStatusText(`Error: ${err.message}`);
    } finally {
      setTimeout(() => setIsBusy(false), 150);
    }
  };

  const goNext = () => {
    if (currentIndex >= poolSize - 1) {
      setStatusText("You are on the last question.");
      return;
    }
    setCurrentIndex(prev => prev + 1);
  };

  const goPrev = () => {
    if (currentIndex <= 0) {
      setStatusText("You are on the first question.");
      return;
    }
    setCurrentIndex(prev => prev - 1);
  };

  const resetSequence = () => {
    if (poolSize > 0) {
      setCurrentIndex(0);
      setStatusText("Reset to the first question.");
    }
  };

  const surpriseCompany = () => {
    if (!companies.length) return;
    const idx = Math.floor(Math.random() * companies.length);
    setCompanyInput(companies[idx]);
    setStatusText(`Surprise company: ${companies[idx]}`);
  };

  const copyLink = () => {
    if (!currentQ || !currentQ.problem_url) {
      setStatusText("No link available.");
      return;
    }
    navigator.clipboard.writeText(currentQ.problem_url).then(() => {
      displayToast("Problem link copied.", "success");
      setStatusText("Link copied.");
    }).catch(() => setStatusText("Could not copy link."));
  };

  const markQuestion = async (isSolved: boolean | null) => {
    if (!currentQ) {
      setStatusText("Load a question first.");
      return;
    }
    if (!user) {
      displayToast("Sign in to save progress.", "warning");
      return;
    }
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
    if (!user) return displayToast("Sign in to save progress.", "warning");
    setIsBusy(true);
    try {
      await API.clearProgress(currentQ.qnum);
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

  const saveComment = async () => {
    if (!user) return displayToast("Sign in to save notes.", "warning");
    if (!currentQ) return;
    const text = commentText.trim();
    if (!text) return displayToast("Write a note first.", "warning");
    
    setIsBusy(true);
    try {
      await API.addComment(currentQ.qnum, text);
      displayToast("Note saved.", "success");
      setCommentMeta(`Last updated ${new Date().toLocaleDateString()}`);
    } catch (err: any) {
      displayToast(`Failed to save note: ${err.message}`, "error");
    } finally {
      setIsBusy(false);
    }
  };

  // Keyboard Shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
      const k = e.key.toLowerCase();
      if (k === "n" && poolSize > 0 && currentIndex < poolSize - 1) {
        e.preventDefault();
        goNext();
      }
      if (k === "p" && poolSize > 0 && currentIndex > 0) {
        e.preventDefault();
        goPrev();
      }
      if (k === "l") {
        e.preventDefault();
        loadQuestions();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [currentIndex, poolSize, companyInput, difficultySelect]); // Add dependencies needed for loadQuestions/goNext/goPrev

  // Derived UI Data for current question
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

  const seen = currentIndex >= 0 ? currentIndex + 1 : 0;
  const progressPct = poolSize ? Math.min((seen / poolSize) * 100, 100) : 0;
  
  const hasQ = Boolean(currentQ);

  return (
    <main className="main-content">
      {showToast && (
        <div id="toast" className={`toast toast-${toastType} toast-show`}>
          {toastMsg}
        </div>
      )}
      
      <div className="page-header">
        <h1 style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <Target size={28} className="text-teal" /> Practice
        </h1>
      </div>

      <section className="card-flat section" style={{ padding: '1.5rem', background: 'var(--paper)', borderRadius: 'var(--radius-lg)', border: '1px solid var(--line)' }}>
        <div className="form-row" style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap' }}>
          <div className="control-group" style={{ flex: 1, minWidth: '200px', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            <label htmlFor="companyInput" style={{ fontWeight: 500 }}>Company</label>
            <input 
              id="companyInput" 
              list="companyOptions" 
              placeholder="Type company name" 
              value={companyInput}
              onChange={e => setCompanyInput(e.target.value)}
              style={{ padding: '0.5rem 1rem', borderRadius: 'var(--radius)', border: '1px solid var(--line)', background: 'var(--bg)', color: 'var(--ink)' }}
            />
            <datalist id="companyOptions">
              {companies.map(c => <option key={c} value={c} />)}
            </datalist>
          </div>
          <div className="control-group" style={{ flex: 1, minWidth: '200px', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            <label htmlFor="difficultySelect" style={{ fontWeight: 500 }}>Difficulty</label>
            <select 
              id="difficultySelect"
              value={difficultySelect}
              onChange={e => setDifficultySelect(e.target.value)}
              style={{ padding: '0.5rem 1rem', borderRadius: 'var(--radius)', border: '1px solid var(--line)', background: 'var(--bg)', color: 'var(--ink)' }}
            >
              <option value="easy">Easy</option>
              <option value="medium">Medium</option>
              <option value="hard">Hard</option>
            </select>
          </div>
        </div>
        
        <div className="button-row" style={{ marginTop: '1rem', display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
          <button className="btn btn-primary" type="button" onClick={() => loadQuestions()} disabled={isBusy}>Load Questions</button>
          <button className="btn" type="button" onClick={goPrev} disabled={isBusy || !poolSize || currentIndex <= 0}>⟪ Prev</button>
          <button className="btn" type="button" onClick={goNext} disabled={isBusy || !poolSize || currentIndex >= poolSize - 1}>Next ⟫</button>
          <button className="btn" type="button" onClick={goNext} disabled={isBusy || !poolSize || currentIndex >= poolSize - 1}><Lightbulb size={16} /> Recommend</button>
          <button className="btn" type="button" onClick={resetSequence} disabled={isBusy || !poolSize}><RotateCcw size={16} /> Reset</button>
          <button className="btn" type="button" onClick={surpriseCompany} disabled={isBusy}><Dices size={16} /> Surprise</button>
          <button className="btn" type="button" onClick={copyLink} disabled={!hasQ}><Copy size={16} /> Copy Link</button>
        </div>
      </section>

      <div className="status-bar section" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '1.5rem', marginBottom: '0.5rem', fontSize: '0.9rem', color: 'var(--muted)' }}>
        <span className="status-text">{statusText}</span>
        <div className="status-right">
          <span className="counter-badge" style={{ background: 'var(--sidebar-hover)', padding: '0.2rem 0.5rem', borderRadius: '1rem', color: 'var(--ink)' }}>{seen} / {poolSize}</span>
        </div>
      </div>

      <div className="progress-wrap section" style={{ background: 'var(--line)', height: '4px', borderRadius: '2px', overflow: 'hidden', marginBottom: '2rem' }}>
        <div className="progress-fill" style={{ width: `${progressPct}%`, background: 'var(--teal)', height: '100%', transition: 'width 0.3s ease' }}></div>
      </div>

      {currentQ && (
        <section className="question-card section" aria-live="polite" style={{ background: 'var(--paper)', borderRadius: 'var(--radius-lg)', border: '1px solid var(--line)', padding: '2rem', display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
          <div className="question-head" style={{ borderBottom: '1px solid var(--line)', paddingBottom: '1rem' }}>
            <h2 style={{ fontSize: '1.5rem', marginBottom: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <span className="text-muted" style={{ fontSize: '1.1rem' }}>#{currentIndex + 1}</span> 
              {currentQ.problem_name || "Untitled"}
            </h2>
            <div className="pill-row" style={{ display: 'flex', gap: '0.5rem' }}>
              <span className="pill" style={{ background: 'var(--sidebar-hover)', padding: '0.2rem 0.6rem', borderRadius: '1rem', fontSize: '0.85rem' }}>Difficulty: {currentQ.difficulty || "Unknown"}</span>
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

          <details style={{ marginTop: '1rem' }}>
            <summary style={{ cursor: 'pointer', color: 'var(--muted)' }}>Show Raw JSON</summary>
            <pre className="raw-json" style={{ marginTop: '1rem', whiteSpace: 'pre-wrap', fontFamily: 'var(--font-mono)', fontSize: '0.8rem', background: 'var(--bg)', padding: '1rem', borderRadius: 'var(--radius)', border: '1px solid var(--line)', overflowX: 'auto' }}>
              {JSON.stringify(currentQ.raw || currentQ, null, 2)}
            </pre>
          </details>
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
              className={`btn outcome-btn ${progress.is_solved === true ? "btn-feedback-selected" : ""}`} 
              type="button" 
              onClick={() => markQuestion(true)} 
              disabled={isBusy}
              style={{ background: progress.is_solved === true ? 'var(--teal-soft)' : 'var(--bg)', color: progress.is_solved === true ? 'var(--teal)' : 'var(--ink)', borderColor: progress.is_solved === true ? 'var(--teal)' : 'var(--line)' }}
            >
              <CheckCircle size={16} /> Solved
            </button>
            <button 
              className={`btn outcome-btn ${progress.is_solved === false ? "btn-feedback-selected" : ""}`} 
              type="button" 
              onClick={markUnsolved} 
              disabled={isBusy}
              style={{ background: progress.is_solved === false ? 'var(--red)' : 'var(--bg)', color: progress.is_solved === false ? 'white' : 'var(--ink)', borderColor: progress.is_solved === false ? 'var(--red)' : 'var(--line)' }}
            >
              <XCircle size={16} /> Not Solved
            </button>
            <button 
              className={`btn outcome-btn ${progress.revisit ? "btn-feedback-selected" : ""}`} 
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
              <MessageSquare size={18} className="text-teal" /> Your Notes
            </h3>
          </div>
          <p className="card-subtitle text-muted" style={{ marginBottom: '1rem', fontSize: '0.9rem' }}>Your latest note is auto-loaded here. Save again to overwrite it.</p>
          <div className="comments-list" style={{ marginBottom: '1rem' }}>
            {commentMeta ? (
              <p className="text-muted text-sm">{commentMeta}</p>
            ) : (
              <p className="text-muted text-sm">No note saved yet for this question.</p>
            )}
          </div>
          <div className="comment-input-wrap" style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            <textarea 
              value={commentText}
              onChange={e => setCommentText(e.target.value)}
              placeholder="Write a note or comment..." 
              rows={2}
              style={{ width: '100%', padding: '0.75rem', borderRadius: 'var(--radius)', border: '1px solid var(--line)', background: 'var(--bg)', color: 'var(--ink)', resize: 'vertical' }}
            />
            <button className="btn btn-primary btn-sm" style={{ alignSelf: 'flex-start' }} type="button" onClick={saveComment} disabled={isBusy}>
              {commentMeta && commentMeta.includes("Last updated") ? "Update Note" : "Save Note"}
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

export default function PracticePage() {
  return (
    <Suspense fallback={<Spinner text="Loading..." />}>
      <PracticeContent />
    </Suspense>
  );
}
