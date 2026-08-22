"use client";

import React from "react";
import DOMPurify from "dompurify";

interface LeetCodeRendererProps {
  content: string;
  className?: string;
}

/**
 * Normalizes LaTeX expressions and mathematical notation commonly found in LeetCode descriptions.
 */
export function formatLeetCodeMath(text: string): string {
  if (!text) return "";

  return text
    // Replace textit & textbf
    .replace(/\\textit\{([^}]+)\}/g, "<em>$1</em>")
    .replace(/\\textbf\{([^}]+)\}/g, "<strong>$1</strong>")
    .replace(/\\text\{([^}]+)\}/g, "$1")
    .replace(/\\texttt\{([^}]+)\}/g, "<code class='inline-code'>$1</code>")

    // Math symbols
    .replace(/\\le\b|\\leq\b/g, "≤")
    .replace(/\\ge\b|\\geq\b/g, "≥")
    .replace(/\\ne\b|\\neq\b/g, "≠")
    .replace(/\\times\b/g, "×")
    .replace(/\\cdot\b/g, "·")
    .replace(/\\dots\b|\\ldots\b|\\cdots\b/g, "...")
    .replace(/\\in\b/g, "∈")
    .replace(/\\infty\b/g, "∞")
    .replace(/\\rightarrow\b|\\to\b/g, "→")
    .replace(/\\pm\b/g, "±")

    // Big-O complexity notations
    .replace(/\$\\mathcal\{O\}\(([^$]+)\)\$/g, "<span class='complexity-pill font-mono font-semibold text-cyan-400'>O($1)</span>")
    .replace(/\$O\(([^$]+)\)\$/g, "<span class='complexity-pill font-mono font-semibold text-cyan-400'>O($1)</span>")

    // Exponents: e.g. 10^4 -> 10⁴, 2^{31} - 1 -> 2³¹ - 1
    .replace(/10\^(\d)/g, (_, exp) => `10<sup>${exp}</sup>`)
    .replace(/10\^\{(\d+)\}/g, (_, exp) => `10<sup>${exp}</sup>`)
    .replace(/2\^\{(\d+)\}/g, (_, exp) => `2<sup>${exp}</sup>`)
    .replace(/2\^(\d+)/g, (_, exp) => `2<sup>${exp}</sup>`)

    // Inline math dollars: $var$ -> <code>var</code> or <em>var</em>
    .replace(/\$([^$]+)\$/g, (_, math) => {
      const clean = math.trim();
      // If it looks like a variable or simple code
      if (/^[a-zA-Z0-9_[\]().+\-*=<>≤≥≠\s]+$/.test(clean)) {
        return `<code class="bg-slate-800/80 text-cyan-300 px-1.5 py-0.5 rounded font-mono text-xs border border-cyan-500/20">${clean}</code>`;
      }
      return `<em class="font-serif text-cyan-200">${clean}</em>`;
    });
}

/**
 * Formats structured LeetCode descriptions with dedicated styled Example cards and Constraints panels.
 */
export function LeetCodeRenderer({ content, className = "" }: LeetCodeRendererProps) {
  if (!content) return null;

  // 1. First format LaTeX math in the content
  let formatted = formatLeetCodeMath(content);

  // 2. Parse example blocks:
  // Clean up existing raw tags and wrap examples in clean markdown/HTML structure
  formatted = formatted
    .replace(/<pre>([\s\S]*?)<\/pre>/gi, (match, inner) => {
      return `<div class="my-4 rounded-xl border border-line/60 bg-slate-950 p-4 font-mono text-xs text-slate-200 overflow-x-auto leading-relaxed shadow-sm">${inner}</div>`;
    })
    .replace(/<strong>Constraints:<\/strong>|Constraints:/gi, '<h3 class="text-base font-bold text-white mt-6 mb-3 flex items-center gap-2"><span class="text-cyan-400">❖</span> Constraints</h3>')
    .replace(/<strong>Follow-up:?<\/strong>|Follow-up:?/gi, '<h3 class="text-base font-bold text-amber-300 mt-6 mb-2 flex items-center gap-2"><span class="text-amber-400">✦</span> Follow-up</h3>');

  // Sanitize with DOMPurify
  const sanitizedHtml = DOMPurify.sanitize(formatted, {
    ADD_TAGS: ["sup", "sub", "code", "em", "strong", "span", "div", "pre", "h3", "ul", "li", "ol", "p", "br", "hr", "table", "thead", "tbody", "tr", "th", "td"],
    ADD_ATTR: ["class", "style"],
  });

  return (
    <div
      className={`leetcode-content prose prose-invert max-w-none text-slate-300 text-sm leading-relaxed space-y-4 ${className}`}
      dangerouslySetInnerHTML={{ __html: sanitizedHtml }}
    />
  );
}
