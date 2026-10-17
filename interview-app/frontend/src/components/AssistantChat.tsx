"use client";

import React, { useState, useRef, useEffect, KeyboardEvent } from "react";
import { API } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Bot, Send, Trash2 } from "lucide-react";

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

interface AssistantChatProps {
  questionText: string;
}

function renderInlineMarkdown(text: string): React.ReactNode {
  // Matches inline code `...` or bold **...**
  const tokens = text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g);
  return tokens.map((token, idx) => {
    if (token.startsWith("`") && token.endsWith("`")) {
      return (
        <code
          key={idx}
          style={{
            background: "var(--sidebar-hover)",
            color: "var(--teal)",
            fontFamily: "var(--font-mono)",
            fontSize: "0.85em",
            padding: "0.15rem 0.4rem",
            borderRadius: "4px",
            border: "1px solid var(--line)",
          }}
        >
          {token.slice(1, -1)}
        </code>
      );
    }
    if (token.startsWith("**") && token.endsWith("**")) {
      return (
        <strong key={idx} style={{ fontWeight: 600, color: "var(--ink)" }}>
          {token.slice(2, -2)}
        </strong>
      );
    }
    return token;
  });
}

function AssistantMarkdown({ content }: { content: string }) {
  if (!content) return null;

  // Split by fenced code blocks
  const parts = content.split(/(```[\s\S]*?```)/g);

  return (
    <div className="assistant-markdown" style={{ display: "flex", flexDirection: "column", gap: "0.5rem", fontSize: "0.95rem", lineHeight: 1.6 }}>
      {parts.map((part, partIdx) => {
        if (part.startsWith("```") && part.endsWith("```")) {
          const lines = part.slice(3, -3).split("\n");
          const firstLine = lines[0].trim();
          const hasLang = firstLine && !firstLine.includes(" ") && lines.length > 1;
          const lang = hasLang ? firstLine : "";
          const code = (hasLang ? lines.slice(1) : lines).join("\n").trim();

          return (
            <div
              key={partIdx}
              style={{
                margin: "0.5rem 0",
                borderRadius: "var(--radius)",
                overflow: "hidden",
                border: "1px solid var(--line)",
                background: "var(--sidebar-bg)",
                fontFamily: "var(--font-mono)",
                fontSize: "0.85rem",
              }}
            >
              {lang && (
                <div
                  style={{
                    padding: "0.25rem 0.75rem",
                    background: "var(--sidebar-hover)",
                    borderBottom: "1px solid var(--line)",
                    fontSize: "0.75rem",
                    color: "var(--teal)",
                    fontWeight: 600,
                    textTransform: "uppercase",
                    letterSpacing: "0.5px",
                  }}
                >
                  {lang}
                </div>
              )}
              <pre style={{ margin: 0, padding: "0.75rem 1rem", overflowX: "auto", whiteSpace: "pre-wrap", wordBreak: "break-word", color: "var(--ink)" }}>
                <code>{code}</code>
              </pre>
            </div>
          );
        }

        // Non-code blocks: render paragraphs, headings, bullet/numbered lists
        const lines = part.split(/\r?\n/);
        const elements: React.ReactNode[] = [];
        let listItems: React.ReactNode[] = [];
        let listOrdered = false;

        const flushList = (key: string) => {
          if (listItems.length > 0) {
            if (listOrdered) {
              elements.push(
                <ol key={key} style={{ margin: "0.25rem 0", paddingLeft: "1.3rem" }}>
                  {listItems}
                </ol>
              );
            } else {
              elements.push(
                <ul key={key} style={{ margin: "0.25rem 0", paddingLeft: "1.3rem", listStyleType: "disc" }}>
                  {listItems}
                </ul>
              );
            }
            listItems = [];
          }
        };

        lines.forEach((line, lIdx) => {
          const trimmed = line.trim();
          if (!trimmed) {
            flushList(`list-${lIdx}`);
            return;
          }

          // Bullet items: * or -
          if (/^[-*]\s+/.test(trimmed)) {
            if (listOrdered && listItems.length > 0) flushList(`list-sw-${lIdx}`);
            listOrdered = false;
            listItems.push(
              <li key={lIdx} style={{ margin: "0.15rem 0" }}>
                {renderInlineMarkdown(trimmed.replace(/^[-*]\s+/, ""))}
              </li>
            );
            return;
          }

          // Numbered items: 1. or 2. etc
          const numMatch = trimmed.match(/^(\d+)\.\s+(.*)/);
          if (numMatch) {
            if (!listOrdered && listItems.length > 0) flushList(`list-sw-${lIdx}`);
            listOrdered = true;
            listItems.push(
              <li key={lIdx} style={{ margin: "0.15rem 0" }}>
                {renderInlineMarkdown(numMatch[2])}
              </li>
            );
            return;
          }

          flushList(`list-before-${lIdx}`);

          // Headings
          if (trimmed.startsWith("### ")) {
            elements.push(
              <h4 key={lIdx} style={{ fontSize: "1rem", fontWeight: 600, margin: "0.4rem 0 0.15rem", color: "var(--ink)" }}>
                {renderInlineMarkdown(trimmed.slice(4))}
              </h4>
            );
            return;
          }
          if (trimmed.startsWith("## ")) {
            elements.push(
              <h3 key={lIdx} style={{ fontSize: "1.05rem", fontWeight: 600, margin: "0.5rem 0 0.2rem", color: "var(--ink)" }}>
                {renderInlineMarkdown(trimmed.slice(3))}
              </h3>
            );
            return;
          }
          if (trimmed.startsWith("# ")) {
            elements.push(
              <h2 key={lIdx} style={{ fontSize: "1.15rem", fontWeight: 700, margin: "0.6rem 0 0.25rem", color: "var(--ink)" }}>
                {renderInlineMarkdown(trimmed.slice(2))}
              </h2>
            );
            return;
          }

          // Normal text
          elements.push(
            <p key={lIdx} style={{ margin: "0.2rem 0" }}>
              {renderInlineMarkdown(trimmed)}
            </p>
          );
        });

        flushList(`list-end-${partIdx}`);

        return <React.Fragment key={partIdx}>{elements}</React.Fragment>;
      })}
    </div>
  );
}

export function AssistantChat({ questionText }: AssistantChatProps) {
  const { user } = useAuth();
  const [history, setHistory] = useState<ChatMessage[]>([]);
  const [doubt, setDoubt] = useState("");
  const [inFlight, setInFlight] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");

  const chatMessagesRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    if (chatMessagesRef.current) {
      chatMessagesRef.current.scrollTop = chatMessagesRef.current.scrollHeight;
    }
  }, [history, inFlight]);

  const askAssistant = async () => {
    if (inFlight) return;
    if (!user) {
      setErrorMsg("Please sign in to ask the AI assistant.");
      return;
    }
    if (!questionText.trim()) {
      setErrorMsg("Load a question first.");
      return;
    }
    const currentDoubt = doubt.trim();
    if (!currentDoubt) {
      setErrorMsg("Type your doubt first.");
      return;
    }

    setErrorMsg("");
    const newHistory = [...history, { role: "user" as const, content: currentDoubt }];
    setHistory(newHistory);
    setDoubt("");
    setInFlight(true);

    try {
      const stream = await API.askAssistantStream(questionText, currentDoubt, newHistory.slice(-12));
      const reader = stream.getReader();
      const decoder = new TextDecoder();
      let answerText = "";
      let lineBuffer = "";

      setHistory([...newHistory, { role: "assistant", content: "" }]);

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        lineBuffer += decoder.decode(value, { stream: true });
        const lines = lineBuffer.split("\n");
        lineBuffer = lines.pop() ?? "";

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            const dataStr = line.slice(6).trim();
            if (dataStr) {
              try {
                const data = JSON.parse(dataStr);
                if (data.error) throw new Error(data.error);
                if (data.text) {
                  answerText += data.text;
                  setHistory([...newHistory, { role: "assistant", content: answerText }]);
                }
              } catch(e) {
                if (e instanceof Error && e.message !== "Unexpected end of JSON input" && !e.message.includes("is not valid JSON")) {
                  throw e;
                }
              }
            }
          }
        }
      }
    } catch (err: any) {
      setHistory(prev => {
        const last = prev[prev.length - 1];
        if (last && last.role === "assistant") {
          return [...prev.slice(0, -1), { role: "assistant", content: last.content + (last.content ? "\n\n" : "") + `Error: ${err.message}` }];
        }
        return [...prev, { role: "assistant", content: `Error: ${err.message}` }];
      });
      setErrorMsg(`Assistant error: ${err.message}`);
    } finally {
      setInFlight(false);
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      askAssistant();
    }
  };

  const clearChat = () => {
    setHistory([]);
    setErrorMsg("Chat cleared.");
    setTimeout(() => setErrorMsg(""), 2000);
  };

  return (
    <section className="assistant-panel section" style={{ display: 'flex', flexDirection: 'column', gap: '1rem', background: 'var(--paper)', border: '1px solid var(--line)', borderRadius: 'var(--radius-lg)', padding: '1.5rem' }}>
      <div className="assistant-head">
        <h3 style={{ margin: 0, fontSize: '1.1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <Bot size={20} className="text-teal" /> AI Interview Assistant
        </h3>
      </div>
      <p className="card-subtitle text-muted" style={{ fontSize: '0.9rem', margin: 0 }}>Ask doubts about the current problem. The assistant gives hints, not full solutions.</p>

      <div
        ref={chatMessagesRef}
        className="chat-messages"
        style={{ flex: 1, minHeight: '200px', maxHeight: '450px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '1rem', padding: '1rem', background: 'var(--bg)', borderRadius: 'var(--radius)' }}
      >
        {history.length === 0 ? (
          <p className="chat-empty text-muted" style={{ textAlign: 'center', margin: 'auto' }}>Load a question, then ask your doubt here.</p>
        ) : (
          history.map((item, idx) => (
            <article key={idx} className={`chat-bubble ${item.role}`} style={{ alignSelf: item.role === 'user' ? 'flex-end' : 'flex-start', background: item.role === 'user' ? 'var(--teal-soft)' : 'var(--paper)', color: item.role === 'user' ? 'var(--teal)' : 'var(--ink)', padding: '0.75rem 1rem', borderRadius: 'var(--radius)', border: item.role === 'assistant' ? '1px solid var(--line)' : 'none', maxWidth: '85%' }}>
              <p className="chat-role text-muted" style={{ fontSize: '0.75rem', marginBottom: '0.25rem' }}>{item.role === "assistant" ? "Assistant" : "You"}</p>
              <div className="chat-text" style={{ margin: 0, fontSize: '0.95rem' }}>
                {item.role === "assistant" ? <AssistantMarkdown content={item.content} /> : <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{item.content}</p>}
              </div>
            </article>
          ))
        )}
        {inFlight && (
          <article className="chat-bubble assistant typing-indicator" style={{ alignSelf: 'flex-start', background: 'var(--paper)', border: '1px solid var(--line)', padding: '0.75rem 1rem', borderRadius: 'var(--radius)', maxWidth: '85%' }}>
            <p className="chat-role text-muted" style={{ fontSize: '0.75rem', marginBottom: '0.25rem' }}>Assistant</p>
            <p className="chat-text" style={{ margin: 0, fontSize: '0.95rem' }}>
              <span className="typing-dots" style={{ letterSpacing: '2px' }}>...</span> Thinking...
            </p>
          </article>
        )}
      </div>

      <div className="chat-input-wrap" style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
        <textarea
          value={doubt}
          onChange={(e) => setDoubt(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={inFlight || !questionText}
          placeholder={user ? "Ask about approach, complexity, edge cases..." : "Sign in to ask the AI assistant..."}
          rows={3}
          style={{ width: '100%', padding: '0.75rem', borderRadius: 'var(--radius)', border: '1px solid var(--line)', background: 'var(--bg)', color: 'var(--ink)', resize: 'vertical' }}
        />
        <div className="chat-actions" style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
          <button className="btn btn-primary" type="button" onClick={askAssistant} disabled={inFlight || !questionText || !user}>
            <Send size={15} style={{ marginRight: '0.4rem' }} /> Ask Assistant
          </button>
          <button className="btn" type="button" onClick={clearChat}>
            <Trash2 size={15} style={{ marginRight: '0.4rem' }} /> Clear Chat
          </button>
          {errorMsg && <span className="text-muted" style={{ fontSize: '0.85rem' }}>{errorMsg}</span>}
        </div>
      </div>
    </section>
  );
}
