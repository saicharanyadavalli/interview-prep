"use client";

import React, { useState, useRef, useEffect, KeyboardEvent } from "react";
import { API } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

interface AssistantChatProps {
  questionText: string;
}

export function AssistantChat({ questionText }: AssistantChatProps) {
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

  const normalizeAssistantText = (text: string) => {
    return String(text || "")
      .replace(/\r\n?/g, "\n")
      .replace(/```[\s\S]*?```/g, (b) => b.replace(/```/g, "").trim())
      .replace(/`([^`]+)`/g, "$1")
      .replace(/\*\*([^*]+)\*\*/g, "$1")
      .replace(/\n{3,}/g, "\n\n")
      .trim();
  };

  const askAssistant = async () => {
    if (inFlight) return;
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

      setHistory([...newHistory, { role: "assistant", content: "" }]);

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        
        const chunk = decoder.decode(value, { stream: true });
        const lines = chunk.split("\n");
        
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
        <h3 style={{ margin: 0, fontSize: '1.1rem' }}>🤖 AI Interview Assistant</h3>
      </div>
      <p className="card-subtitle text-muted" style={{ fontSize: '0.9rem', margin: 0 }}>Ask doubts about the current problem. The assistant gives hints, not full solutions.</p>
      
      <div 
        ref={chatMessagesRef}
        className="chat-messages" 
        style={{ flex: 1, minHeight: '200px', maxHeight: '400px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '1rem', padding: '1rem', background: 'var(--bg)', borderRadius: 'var(--radius)' }}
      >
        {history.length === 0 ? (
          <p className="chat-empty text-muted" style={{ textAlign: 'center', margin: 'auto' }}>Load a question, then ask your doubt here.</p>
        ) : (
          history.map((item, idx) => (
            <article key={idx} className={`chat-bubble ${item.role}`} style={{ alignSelf: item.role === 'user' ? 'flex-end' : 'flex-start', background: item.role === 'user' ? 'var(--teal-soft)' : 'var(--paper)', color: item.role === 'user' ? 'var(--teal)' : 'var(--ink)', padding: '0.75rem 1rem', borderRadius: 'var(--radius)', border: item.role === 'assistant' ? '1px solid var(--line)' : 'none', maxWidth: '85%' }}>
              <p className="chat-role text-muted" style={{ fontSize: '0.75rem', marginBottom: '0.25rem' }}>{item.role === "assistant" ? "Assistant" : "You"}</p>
              <p className="chat-text" style={{ whiteSpace: 'pre-wrap', margin: 0, fontSize: '0.95rem' }}>
                {item.role === "assistant" ? normalizeAssistantText(item.content) : item.content}
              </p>
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
          placeholder="Ask about approach, complexity, edge cases..." 
          rows={3}
          style={{ width: '100%', padding: '0.75rem', borderRadius: 'var(--radius)', border: '1px solid var(--line)', background: 'var(--bg)', color: 'var(--ink)', resize: 'vertical' }}
        />
        <div className="chat-actions" style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
          <button className="btn btn-primary" type="button" onClick={askAssistant} disabled={inFlight || !questionText}>Ask Assistant</button>
          <button className="btn" type="button" onClick={clearChat}>Clear Chat</button>
          {errorMsg && <span className="text-muted" style={{ fontSize: '0.85rem' }}>{errorMsg}</span>}
        </div>
      </div>
    </section>
  );
}
