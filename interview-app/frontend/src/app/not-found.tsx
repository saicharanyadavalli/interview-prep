import React from "react";
import Link from "next/link";
import { FileQuestion, Compass, LayoutDashboard } from "lucide-react";

export default function NotFound() {
  return (
    <main
      className="main-content"
      style={{
        minHeight: "75vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "2rem 1rem",
      }}
    >
      <div
        className="card-flat"
        style={{
          background: "var(--paper)",
          border: "1px solid var(--line)",
          borderRadius: "var(--radius-lg)",
          boxShadow: "var(--shadow)",
          padding: "3rem 2rem",
          maxWidth: "520px",
          width: "100%",
          textAlign: "center",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
        }}
      >
        <div
          style={{
            width: "72px",
            height: "72px",
            borderRadius: "50%",
            background: "var(--teal-soft)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            marginBottom: "1.5rem",
            color: "var(--teal)",
          }}
        >
          <FileQuestion size={40} strokeWidth={1.75} aria-hidden="true" />
        </div>

        <span
          style={{
            fontSize: "0.85rem",
            fontWeight: 700,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            color: "var(--teal)",
            marginBottom: "0.5rem",
          }}
        >
          Error 404
        </span>

        <h1
          style={{
            fontSize: "1.85rem",
            fontWeight: 700,
            color: "var(--ink)",
            marginBottom: "0.75rem",
            lineHeight: 1.25,
          }}
        >
          404 - Page Not Found
        </h1>

        <p
          style={{
            fontSize: "0.95rem",
            color: "var(--muted)",
            lineHeight: 1.6,
            marginBottom: "2rem",
            maxWidth: "420px",
          }}
        >
          The page you are looking for might have been removed, had its name changed, or is temporarily unavailable.
        </p>

        <div
          style={{
            display: "flex",
            gap: "0.75rem",
            flexWrap: "wrap",
            justifyContent: "center",
            width: "100%",
          }}
        >
          <Link
            href="/dashboard"
            className="btn btn-primary"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "0.5rem",
              padding: "0.65rem 1.4rem",
              fontWeight: 600,
            }}
          >
            <LayoutDashboard size={18} />
            Go to Dashboard
          </Link>
          <Link
            href="/questions"
            className="btn"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "0.5rem",
              padding: "0.65rem 1.4rem",
              fontWeight: 600,
              background: "var(--surface-chip)",
              borderColor: "var(--line)",
              color: "var(--ink)",
            }}
          >
            <Compass size={18} />
            Browse Questions
          </Link>
        </div>
      </div>
    </main>
  );
}
