"use client";

import React, { useState, useRef, useEffect, KeyboardEvent } from "react";
import { API } from "@/lib/api";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Bot, Send, Trash2, Sparkles } from "lucide-react";

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
              } catch (e) {
                if (e instanceof Error && e.message !== "Unexpected end of JSON input" && !e.message.includes("is not valid JSON")) {
                  throw e;
                }
              }
            }
          }
        }
      }
    } catch (err: any) {
      setHistory((prev) => {
        const last = prev[prev.length - 1];
        if (last && last.role === "assistant") {
          return [
            ...prev.slice(0, -1),
            { role: "assistant", content: last.content + (last.content ? "\n\n" : "") + `Error: ${err.message}` },
          ];
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
    setErrorMsg("");
  };

  return (
    <Card variant="default" className="flex flex-col h-[500px] border-zinc-800 bg-zinc-900/90 shadow-2xl p-4 space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-zinc-800 pb-3">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-cyan-500/10 border border-cyan-500/20 flex items-center justify-center text-cyan-400">
            <Bot size={16} />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-zinc-100 flex items-center gap-1.5">
              AI Doubt Assistant <Sparkles size={12} className="text-cyan-400" />
            </h3>
            <p className="text-[11px] text-zinc-400">Ask for hints, complexity analysis, or approach tips.</p>
          </div>
        </div>
        {history.length > 0 && (
          <Button variant="ghost" size="sm" onClick={clearChat} title="Clear Chat">
            <Trash2 size={14} />
          </Button>
        )}
      </div>

      {/* Message History with ARIA Live Region */}
      <div
        ref={chatMessagesRef}
        aria-live="polite"
        aria-atomic="false"
        className="flex-1 overflow-y-auto space-y-3 pr-1 text-xs"
      >
        {history.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center text-zinc-500 p-6 space-y-2">
            <Bot size={32} className="text-zinc-600" />
            <p>Ask any doubt about the current problem statement.</p>
          </div>
        ) : (
          history.map((item, idx) => (
            <div
              key={idx}
              className={`flex flex-col ${item.role === "user" ? "items-end" : "items-start"}`}
            >
              <span className="text-[10px] text-zinc-500 mb-1 px-1">
                {item.role === "user" ? "You" : "AI Assistant"}
              </span>
              <div
                className={`max-w-[88%] p-3 rounded-xl leading-relaxed whitespace-pre-wrap ${
                  item.role === "user"
                    ? "bg-cyan-600 text-white font-medium rounded-tr-none"
                    : "bg-zinc-800/90 text-zinc-200 border border-zinc-700/60 rounded-tl-none"
                }`}
              >
                {item.role === "assistant" ? normalizeAssistantText(item.content) : item.content}
              </div>
            </div>
          ))
        )}
        {inFlight && (
          <div className="flex flex-col items-start">
            <span className="text-[10px] text-zinc-500 mb-1 px-1">AI Assistant</span>
            <div className="bg-zinc-800/90 text-zinc-400 border border-zinc-700/60 p-3 rounded-xl rounded-tl-none animate-pulse">
              Thinking...
            </div>
          </div>
        )}
      </div>

      {/* Input Form */}
      <div className="pt-2 border-t border-zinc-800 space-y-2">
        <textarea
          value={doubt}
          onChange={(e) => setDoubt(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={inFlight || !questionText}
          placeholder="Ask a question or request a hint (Shift+Enter for newline)..."
          rows={2}
          className="w-full bg-zinc-950/80 border border-zinc-800 rounded-lg p-2.5 text-xs text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-cyan-500 resize-none"
        />
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-rose-400">{errorMsg}</span>
          <Button
            size="sm"
            onClick={askAssistant}
            isLoading={inFlight}
            disabled={inFlight || !doubt.trim() || !questionText}
            rightIcon={<Send size={12} />}
          >
            Ask Assistant
          </Button>
        </div>
      </div>
    </Card>
  );
}
