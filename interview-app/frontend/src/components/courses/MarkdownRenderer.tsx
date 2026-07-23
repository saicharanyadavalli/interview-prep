"use client";

import React from "react";
import DOMPurify from 'dompurify';

interface MarkdownRendererProps {
  content: string;
}

export function MarkdownRenderer({ content }: MarkdownRendererProps) {
  if (!content) return null;

  // Check if content is raw HTML (e.g. system design HTML step lessons)
  const trimmedContent = content.trim();
  if (trimmedContent.startsWith("<") || /<[a-z][\s\S]*>/i.test(trimmedContent)) {
    const sanitizedHtml = content
      .replace(/<link\s+[^>]*rel=["']stylesheet["'][^>]*>/gi, '')
      .replace(/href="(?:\.\.\/)+system-design\.html"/gi, 'href="/courses/system-design"')
      .replace(/href="step-(\d+)\.html"/gi, 'href="/courses/system-design/step-$1"')
      .replace(/href="\.\.\/\.\.\/([a-z0-9-]+)\.html"/gi, 'href="/courses/$1"');

    return (
      <div 
        className="html-lesson-content prose prose-invert w-full max-w-none break-words text-gray-300 leading-relaxed space-y-4"
        dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(sanitizedHtml) }}
      />
    );
  }

  // Split content into blocks by double newlines or block elements
  const lines = content.split(/\r?\n/);
  const elements: React.ReactNode[] = [];
  let inCodeBlock = false;
  let codeBuffer: string[] = [];
  let codeLang = "";
  let tableBuffer: string[] = [];
  let listBuffer: string[] = [];

  const flushList = (key: string) => {
    if (listBuffer.length > 0) {
      elements.push(
        <ul key={key} className="list-disc list-inside space-y-1.5 my-3 text-gray-300">
          {listBuffer.map((item, idx) => (
            <li key={idx} className="leading-relaxed">
              {renderFormattedText(item)}
            </li>
          ))}
        </ul>
      );
      listBuffer = [];
    }
  };

  const flushTable = (key: string) => {
    if (tableBuffer.length > 0) {
      const rows = tableBuffer.map((row) =>
        row
          .split("|")
          .map((c) => c.trim())
          .filter((_, idx, arr) => idx > 0 && idx < arr.length - 1)
      );

      // Filter out header separator row if present (e.g. ---|---)
      const headerRow = rows[0] || [];
      const bodyRows = rows.slice(1).filter((r) => !r.every((cell) => /^[-:\s]+$/.test(cell)));

      elements.push(
        <div key={key} className="my-4 overflow-x-auto rounded-xl border border-line/60 bg-paper/60 shadow-sm">
          <table className="w-full text-left text-sm">
            {headerRow.length > 0 && (
              <thead className="bg-slate-800/80 text-teal font-semibold border-b border-line/60">
                <tr>
                  {headerRow.map((col, idx) => (
                    <th key={idx} className="px-4 py-2.5 border-r last:border-r-0 border-line/40">
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
            )}
            <tbody>
              {bodyRows.map((row, rIdx) => (
                <tr key={rIdx} className="border-b last:border-b-0 border-line/30 hover:bg-slate-800/40">
                  {row.map((cell, cIdx) => (
                    <th key={cIdx} className="px-4 py-2 border-r last:border-r-0 border-line/30 font-normal text-gray-300">
                      {cell}
                    </th>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
      tableBuffer = [];
    }
  };

  const renderFormattedText = (text: string): React.ReactNode => {
    // Handle inline code: `code`
    const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g);
    return parts.map((part, idx) => {
      if (part.startsWith("`") && part.endsWith("`")) {
        return (
          <code key={idx} className="bg-slate-800 text-teal-light font-mono px-1.5 py-0.5 rounded text-xs border border-teal/20">
            {part.slice(1, -1)}
          </code>
        );
      }
      if (part.startsWith("**") && part.endsWith("**")) {
        return (
          <strong key={idx} className="font-semibold text-white">
            {part.slice(2, -2)}
          </strong>
        );
      }
      return part;
    });
  };

  lines.forEach((line, index) => {
    const trimmed = line.trim();

    // Code block start/end
    if (trimmed.startsWith("```")) {
      if (inCodeBlock) {
        // End code block
        elements.push(
          <div key={`code-${index}`} className="my-4 rounded-xl overflow-hidden border border-line/60 bg-slate-900/90 font-mono text-xs">
            {codeLang && (
              <div className="px-4 py-1.5 bg-slate-800/80 text-gray-400 font-sans text-xs border-b border-line/40 flex justify-between items-center">
                <span>{codeLang.toUpperCase()}</span>
              </div>
            )}
            <pre className="p-4 text-emerald-400 overflow-x-auto whitespace-pre-wrap leading-relaxed">
              <code>{codeBuffer.join("\n")}</code>
            </pre>
          </div>
        );
        codeBuffer = [];
        codeLang = "";
        inCodeBlock = false;
      } else {
        flushList(`list-${index}`);
        flushTable(`table-${index}`);
        inCodeBlock = true;
        codeLang = trimmed.slice(3).trim();
      }
      return;
    }

    if (inCodeBlock) {
      codeBuffer.push(line);
      return;
    }

    // Tables
    if (trimmed.startsWith("|") && trimmed.endsWith("|")) {
      flushList(`list-${index}`);
      tableBuffer.push(trimmed);
      return;
    } else if (tableBuffer.length > 0) {
      flushTable(`table-${index}`);
    }

    // Unordered List Items
    if (/^[-*]\s+/.test(trimmed)) {
      listBuffer.push(trimmed.replace(/^[-*]\s+/, ""));
      return;
    } else if (listBuffer.length > 0) {
      flushList(`list-${index}`);
    }

    // Headings
    if (trimmed.startsWith("# ")) {
      elements.push(
        <h1 key={index} className="text-2xl font-bold text-white mt-6 mb-3 border-b border-line/40 pb-2">
          {renderFormattedText(trimmed.slice(2))}
        </h1>
      );
      return;
    }
    if (trimmed.startsWith("## ")) {
      elements.push(
        <h2 key={index} className="text-xl font-bold text-white mt-5 mb-2">
          {renderFormattedText(trimmed.slice(3))}
        </h2>
      );
      return;
    }
    if (trimmed.startsWith("### ")) {
      elements.push(
        <h3 key={index} className="text-lg font-semibold text-white mt-4 mb-2">
          {renderFormattedText(trimmed.slice(4))}
        </h3>
      );
      return;
    }

    // Blockquote
    if (trimmed.startsWith("> ")) {
      elements.push(
        <blockquote key={index} className="border-l-4 border-teal bg-teal-soft/10 p-3 my-3 text-gray-300 rounded-r-lg text-sm italic">
          {renderFormattedText(trimmed.slice(2))}
        </blockquote>
      );
      return;
    }

    // Empty line
    if (!trimmed) {
      return;
    }

    // Standard Paragraph
    elements.push(
      <p key={index} className="my-2.5 text-gray-300 text-sm leading-relaxed">
        {renderFormattedText(trimmed)}
      </p>
    );
  });

  // Flush remaining buffers
  flushList("list-end");
  flushTable("table-end");

  return <div className="markdown-content w-full max-w-none break-words">{elements}</div>;
}
