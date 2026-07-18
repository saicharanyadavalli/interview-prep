"use client";

import React from "react";
import Link from "next/link";
import { Brain, Code, Award, Calendar, ChevronRight, Layout, ShieldCheck, Flame, BookOpen } from "lucide-react";

export default function LandingPage() {
  return (
    <div 
      className="landing-container w-full" 
      style={{ 
        color: "var(--ink)", 
        background: "var(--bg)", 
        minHeight: "100vh", 
        fontFamily: "var(--font-space-grotesk), sans-serif",
        overflowX: "hidden"
      }}
    >
      {/* Navbar */}
      <header 
        style={{ 
          display: "flex", 
          justifyContent: "space-between", 
          alignItems: "center", 
          padding: "1.5rem 2rem", 
          maxWidth: "1200px", 
          margin: "0 auto",
          borderBottom: "1px solid var(--line)"
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
          <img src="/assets/logo-mark.svg" alt="Logo" style={{ width: "32px", height: "32px" }} />
          <span style={{ fontWeight: 700, fontSize: "1.25rem", letterSpacing: "-0.025em" }}>Interview Assistant</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "1.5rem" }}>
          <Link href="/login" style={{ color: "var(--muted)", textDecoration: "none", fontSize: "0.95rem", fontWeight: 500 }}>
            Sign In
          </Link>
          <Link 
            href="/login" 
            className="btn btn-primary btn-sm" 
            style={{ 
              borderRadius: "var(--radius-sm)", 
              padding: "0.5rem 1.25rem",
              display: "inline-flex",
              alignItems: "center"
            }}
          >
            Get Started <ChevronRight size={16} style={{ marginLeft: "4px" }} />
          </Link>
        </div>
      </header>

      {/* Hero Section */}
      <section 
        style={{ 
          maxWidth: "1000px", 
          margin: "0 auto", 
          padding: "6rem 2rem 4rem", 
          textAlign: "center",
          position: "relative"
        }}
      >
        <div 
          style={{ 
            display: "inline-flex", 
            alignItems: "center", 
            gap: "0.5rem", 
            background: "rgba(34, 211, 238, 0.08)", 
            border: "1px solid rgba(34, 211, 238, 0.2)", 
            color: "var(--teal)", 
            padding: "0.4rem 1rem", 
            borderRadius: "9999px",
            fontSize: "0.85rem",
            fontWeight: 600,
            marginBottom: "2rem"
          }}
        >
          <Flame size={14} /> AI-Powered Coding Practice Platform
        </div>
        <h1 
          style={{ 
            fontSize: "clamp(2.5rem, 5vw, 4rem)", 
            fontWeight: 700, 
            lineHeight: 1.1,
            letterSpacing: "-0.03em",
            marginBottom: "1.5rem"
          }}
        >
          Master Technical Interviews <br />
          <span style={{ color: "var(--teal)" }}>With Interactive AI Guidance</span>
        </h1>
        <p 
          style={{ 
            fontSize: "clamp(1.1rem, 2vw, 1.25rem)", 
            color: "var(--muted)", 
            maxWidth: "680px", 
            margin: "0 auto 3rem",
            lineHeight: 1.5
          }}
        >
          Structure your DSA and System Design prep, build long-term practice consistency, and solve complex problems with an interactive AI tutor trained to coach you.
        </p>

        <div style={{ display: "flex", gap: "1rem", justifyContent: "center" }}>
          <Link 
            href="/login" 
            className="btn btn-primary" 
            style={{ 
              padding: "0.75rem 2rem", 
              borderRadius: "var(--radius)",
              display: "inline-flex",
              alignItems: "center",
              fontSize: "1.05rem"
            }}
          >
            Start Preparing Free
          </Link>
          <a 
            href="#features" 
            className="btn" 
            style={{ 
              padding: "0.75rem 2rem", 
              borderRadius: "var(--radius)",
              background: "transparent",
              border: "1px solid var(--line)",
              color: "var(--ink)",
              display: "inline-flex",
              alignItems: "center",
              fontSize: "1.05rem",
              textDecoration: "none"
            }}
          >
            Explore Features
          </a>
        </div>
      </section>

      {/* Preview Section / Mock Dashboard */}
      <section style={{ maxWidth: "1100px", margin: "0 auto 8rem", padding: "0 2rem" }}>
        <div 
          style={{ 
            background: "var(--paper)", 
            border: "1px solid var(--line)", 
            borderRadius: "var(--radius-lg)",
            padding: "2rem",
            boxShadow: "var(--shadow)",
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
            gap: "2rem",
            position: "relative"
          }}
        >
          {/* Mock Widget 1 */}
          <div style={{ background: "var(--bg)", border: "1px solid var(--line)", borderRadius: "var(--radius)", padding: "1.25rem" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
              <span style={{ fontWeight: 600, fontSize: "0.95rem" }}>Practice Streak</span>
              <span style={{ color: "var(--teal)", background: "rgba(34, 211, 238, 0.08)", padding: "0.25rem 0.6rem", borderRadius: "9999px", fontSize: "0.75rem", fontWeight: 600 }}>Active</span>
            </div>
            <div style={{ display: "flex", gap: "0.5rem" }}>
              {[1, 2, 3, 4, 5, 6, 7].map((day) => (
                <div 
                  key={day} 
                  style={{ 
                    flex: 1, 
                    height: "36px", 
                    background: day <= 3 ? "var(--teal)" : "var(--line)", 
                    borderRadius: "4px",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: "0.75rem",
                    fontWeight: 600,
                    color: day <= 3 ? "var(--paper)" : "var(--muted)"
                  }}
                >
                  D{day}
                </div>
              ))}
            </div>
          </div>

          {/* Mock Widget 2 */}
          <div style={{ background: "var(--bg)", border: "1px solid var(--line)", borderRadius: "var(--radius)", padding: "1.25rem" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
              <span style={{ fontWeight: 600, fontSize: "0.95rem" }}>Difficulty Distribution</span>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
              <div>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.8rem", color: "var(--muted)", marginBottom: "0.25rem" }}>
                  <span>Easy</span>
                  <span>14 / 20</span>
                </div>
                <div style={{ width: "100%", height: "6px", background: "var(--line)", borderRadius: "9999px", overflow: "hidden" }}>
                  <div style={{ width: "70%", height: "100%", background: "var(--teal)", borderRadius: "9999px" }} />
                </div>
              </div>
              <div>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.8rem", color: "var(--muted)", marginBottom: "0.25rem" }}>
                  <span>Medium</span>
                  <span>8 / 25</span>
                </div>
                <div style={{ width: "100%", height: "6px", background: "var(--line)", borderRadius: "9999px", overflow: "hidden" }}>
                  <div style={{ width: "32%", height: "100%", background: "var(--amber)", borderRadius: "9999px" }} />
                </div>
              </div>
            </div>
          </div>

          {/* Mock Widget 3 */}
          <div style={{ background: "var(--bg)", border: "1px solid var(--line)", borderRadius: "var(--radius)", padding: "1.25rem" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
              <span style={{ fontWeight: 600, fontSize: "0.95rem" }}>AI Assistant Doubt Clearing</span>
            </div>
            <div style={{ fontSize: "0.85rem", color: "var(--muted)", fontStyle: "italic", background: "var(--paper)", padding: "0.75rem", borderRadius: "var(--radius-sm)", border: "1px solid var(--line)" }}>
              "Since we need O(1) random lookup, an Array is preferred over a Linked List. Try maintaining the index hash..."
            </div>
          </div>
        </div>
      </section>

      {/* Features Grid */}
      <section id="features" style={{ background: "var(--paper)", borderTop: "1px solid var(--line)", borderBottom: "1px solid var(--line)", padding: "8rem 2rem" }}>
        <div style={{ maxWidth: "1200px", margin: "0 auto" }}>
          <div style={{ textAlign: "center", marginBottom: "5rem" }}>
            <h2 style={{ fontSize: "2rem", fontWeight: 700, letterSpacing: "-0.02em", marginBottom: "1rem" }}>Everything you need to land the offer</h2>
            <p style={{ color: "var(--muted)", maxWidth: "560px", margin: "0 auto" }}>Engineered to build consistency, strengthen recall, and clarify design patterns.</p>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(250px, 1fr))", gap: "2rem" }}>
            {/* Feature 1 */}
            <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
              <div style={{ width: "40px", height: "40px", borderRadius: "var(--radius-sm)", background: "rgba(34, 211, 238, 0.08)", color: "var(--teal)", display: "flex", alignItems: "center", justifyCentent: "center", paddingLeft: "11px" }}>
                <Brain size={18} />
              </div>
              <h3 style={{ fontSize: "1.2rem", fontWeight: 600 }}>Interactive AI Assistant</h3>
              <p style={{ color: "var(--muted)", fontSize: "0.92rem", lineHeight: 1.5 }}>
                Chat in real-time right alongside the problem workspace. Get targeted hints, run code walkthroughs, and clarify logic without copy-pasting code.
              </p>
            </div>

            {/* Feature 2 */}
            <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
              <div style={{ width: "40px", height: "40px", borderRadius: "var(--radius-sm)", background: "rgba(34, 211, 238, 0.08)", color: "var(--teal)", display: "flex", alignItems: "center", justifyCentent: "center", paddingLeft: "11px" }}>
                <BookOpen size={18} />
              </div>
              <h3 style={{ fontSize: "1.2rem", fontWeight: 600 }}>Structured Learning Tracks</h3>
              <p style={{ color: "var(--muted)", fontSize: "0.92rem", lineHeight: 1.5 }}>
                Follow comprehensive, chapter-based courses on complex topics like System Design. Track track-by-track completions and check off milestones.
              </p>
            </div>

            {/* Feature 3 */}
            <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
              <div style={{ width: "40px", height: "40px", borderRadius: "var(--radius-sm)", background: "rgba(34, 211, 238, 0.08)", color: "var(--teal)", display: "flex", alignItems: "center", justifyCentent: "center", paddingLeft: "11px" }}>
                <Calendar size={18} />
              </div>
              <h3 style={{ fontSize: "1.2rem", fontWeight: 600 }}>Spaced Repetition Queue</h3>
              <p style={{ color: "var(--muted)", fontSize: "0.92rem", lineHeight: 1.5 }}>
                Flag hard questions into your persistent Revisit Queue. Spaced interval trackers remind you to retry questions you haven't fully mastered.
              </p>
            </div>

            {/* Feature 4 */}
            <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
              <div style={{ width: "40px", height: "40px", borderRadius: "var(--radius-sm)", background: "rgba(34, 211, 238, 0.08)", color: "var(--teal)", display: "flex", alignItems: "center", justifyCentent: "center", paddingLeft: "11px" }}>
                <Award size={18} />
              </div>
              <h3 style={{ fontSize: "1.2rem", fontWeight: 600 }}>Interactive Analytics</h3>
              <p style={{ color: "var(--muted)", fontSize: "0.92rem", lineHeight: 1.5 }}>
                Visualize your learning with interactive 30-day activity calendars, topic breakdowns, difficulty rings, and milestone badges.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* CTA Section */}
      <section style={{ maxWidth: "800px", margin: "0 auto", padding: "8rem 2rem", textAlign: "center" }}>
        <h2 style={{ fontSize: "2.2rem", fontWeight: 700, letterSpacing: "-0.025em", marginBottom: "1rem" }}>Start your preparation today</h2>
        <p style={{ color: "var(--muted)", maxWidth: "500px", margin: "0 auto 2.5rem", lineHeight: 1.5 }}>
          Create your account for free and begin tracking your path toward your dream offer.
        </p>
        <Link 
          href="/login" 
          className="btn btn-primary" 
          style={{ 
            padding: "0.85rem 2.5rem", 
            borderRadius: "var(--radius)",
            fontSize: "1.05rem"
          }}
        >
          Get Started Free
        </Link>
      </section>

      {/* Footer */}
      <footer style={{ borderTop: "1px solid var(--line)", padding: "3rem 2rem", background: "var(--paper)" }}>
        <div style={{ maxWidth: "1200px", margin: "0 auto", display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: "2rem", alignItems: "center", fontSize: "0.88rem", color: "var(--muted)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <img src="/assets/logo-mark.svg" alt="Logo" style={{ width: "20px", height: "20px" }} />
            <span style={{ fontWeight: 600, color: "var(--ink)" }}>Interview Assistant</span>
          </div>
          <div>
            © 2026 Interview Assistant. Sharpen your skills responsibly.
          </div>
        </div>
      </footer>
    </div>
  );
}
