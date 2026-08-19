"use client";

import React from "react";
import Image from "next/image";
import Link from "next/link";
import { Brain, Code, Award, Calendar, ChevronRight, Layout, ShieldCheck, Flame, BookOpen, Sparkles, Terminal, CheckCircle2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";

export default function LandingPage() {
  return (
    <div className="landing-container w-full min-h-screen bg-zinc-950 text-zinc-100 font-sans overflow-x-hidden selection:bg-cyan-500 selection:text-white">
      {/* Mesh Glow Backdrop */}
      <div className="fixed inset-0 pointer-events-none z-0 overflow-hidden">
        <div className="absolute -top-40 -right-40 w-[600px] h-[600px] bg-cyan-600/10 rounded-full blur-[140px]" />
        <div className="absolute top-1/3 -left-40 w-[500px] h-[500px] bg-indigo-600/10 rounded-full blur-[140px]" />
        <div className="absolute -bottom-40 right-1/4 w-[600px] h-[600px] bg-cyan-500/10 rounded-full blur-[140px]" />
      </div>

      {/* Header */}
      <header className="relative z-10 max-w-7xl mx-auto px-6 py-5 flex items-center justify-between border-b border-zinc-800/60 backdrop-blur-md">
        <div className="flex items-center gap-3">
          <Image src="/assets/logo-mark.svg" alt="Logo" width={28} height={28} className="w-7 h-7" />
          <span className="font-bold text-lg tracking-tight text-white">Interview Assistant</span>
        </div>
        <div className="flex items-center gap-4">
          <Link href="/login" className="text-sm text-zinc-400 hover:text-zinc-100 font-medium transition-colors">
            Sign In
          </Link>
          <Link href="/login">
            <Button size="sm" rightIcon={<ChevronRight size={14} />}>
              Get Started
            </Button>
          </Link>
        </div>
      </header>

      {/* Hero Section */}
      <section className="relative z-10 max-w-5xl mx-auto pt-20 pb-16 px-6 text-center">
        <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-cyan-500/10 border border-cyan-500/20 text-cyan-400 text-xs font-semibold mb-8 backdrop-blur-sm animate-in fade-in slide-in-from-top-4 duration-500">
          <Flame size={14} className="text-cyan-400 animate-pulse" /> Next-Gen Technical Interview Prep Platform
        </div>
        
        <h1 className="text-4xl md:text-6xl font-extrabold tracking-tight text-white leading-tight mb-6 max-w-4xl mx-auto">
          Master Technical Interviews <br />
          <span className="bg-gradient-to-r from-cyan-400 via-teal-300 to-indigo-400 bg-clip-text text-transparent">
            With Interactive AI Guidance
          </span>
        </h1>
        
        <p className="text-lg md:text-xl text-zinc-400 max-w-2xl mx-auto mb-10 leading-relaxed font-normal">
          Structure your DSA and System Design preparation, build long-term practice consistency, and solve complex problems with an interactive AI tutor trained to coach you.
        </p>

        <div className="flex flex-col sm:flex-row gap-4 justify-center items-center max-w-sm mx-auto mb-16">
          <Link href="/login" className="w-full sm:w-auto">
            <Button size="lg" className="w-full sm:w-auto text-base px-8 py-3.5 shadow-lg shadow-cyan-950/50" rightIcon={<Sparkles size={18} />}>
              Start Preparing Free
            </Button>
          </Link>
          <a href="#features" className="w-full sm:w-auto">
            <Button variant="outline" size="lg" className="w-full sm:w-auto text-base px-6 py-3.5 border-zinc-800 hover:border-zinc-700">
              Explore Features
            </Button>
          </a>
        </div>

        {/* Live Interactive Showcase Mockup */}
        <div className="relative max-w-5xl mx-auto rounded-2xl border border-zinc-800/80 bg-zinc-900/80 p-3 shadow-2xl backdrop-blur-xl">
          <div className="flex items-center gap-2 px-3 py-2 border-b border-zinc-800/80 text-xs text-zinc-400 mb-3">
            <div className="flex gap-1.5">
              <span className="w-3 h-3 rounded-full bg-rose-500/80 inline-block" />
              <span className="w-3 h-3 rounded-full bg-amber-500/80 inline-block" />
              <span className="w-3 h-3 rounded-full bg-emerald-500/80 inline-block" />
            </div>
            <span className="ml-2 font-mono text-zinc-500">interview-assistant // practice-workspace</span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-left p-2">
            <Card variant="subtle" className="p-4 space-y-3">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-sm text-zinc-200">Practice Heatmap</span>
                <Badge variant="cyan" size="sm">Active Streak</Badge>
              </div>
              <div className="grid grid-cols-7 gap-1.5 pt-2">
                {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14].map((day) => (
                  <div
                    key={day}
                    className={`h-7 rounded flex items-center justify-center text-[10px] font-bold ${
                      day <= 10 ? "bg-cyan-600/80 text-white" : "bg-zinc-800 text-zinc-500"
                    }`}
                  >
                    D{day}
                  </div>
                ))}
              </div>
            </Card>

            <Card variant="subtle" className="p-4 space-y-3">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-sm text-zinc-200">Difficulty Matrix</span>
                <span className="text-xs text-zinc-400 font-mono">1081 Questions</span>
              </div>
              <div className="space-y-2.5 pt-1">
                <div>
                  <div className="flex justify-between text-xs text-zinc-400 mb-1">
                    <span>Easy</span>
                    <span className="text-emerald-400 font-medium">142 / 448</span>
                  </div>
                  <div className="h-2 rounded-full bg-zinc-800 overflow-hidden">
                    <div className="h-full bg-emerald-500 rounded-full w-[31%]" />
                  </div>
                </div>
                <div>
                  <div className="flex justify-between text-xs text-zinc-400 mb-1">
                    <span>Medium</span>
                    <span className="text-amber-400 font-medium">89 / 529</span>
                  </div>
                  <div className="h-2 rounded-full bg-zinc-800 overflow-hidden">
                    <div className="h-full bg-amber-500 rounded-full w-[17%]" />
                  </div>
                </div>
                <div>
                  <div className="flex justify-between text-xs text-zinc-400 mb-1">
                    <span>Hard</span>
                    <span className="text-rose-400 font-medium">18 / 104</span>
                  </div>
                  <div className="h-2 rounded-full bg-zinc-800 overflow-hidden">
                    <div className="h-full bg-rose-500 rounded-full w-[17%]" />
                  </div>
                </div>
              </div>
            </Card>

            <Card variant="subtle" className="p-4 space-y-3">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-sm text-zinc-200">AI Assistant Tutor</span>
                <Badge variant="solved" size="sm">Online</Badge>
              </div>
              <div className="bg-zinc-950/60 rounded-lg p-3 border border-zinc-800 text-xs space-y-2 font-mono text-zinc-300">
                <p className="text-cyan-400 font-semibold">AI Tutor &gt;</p>
                <p className="leading-relaxed">To optimize 2-Sum to O(N), use a hash map to store complements as you iterate.</p>
              </div>
            </Card>
          </div>
        </div>
      </section>

      {/* Feature Section */}
      <section id="features" className="relative z-10 max-w-6xl mx-auto py-24 px-6 border-t border-zinc-900">
        <div className="text-center max-w-2xl mx-auto mb-16 space-y-3">
          <h2 className="text-3xl font-bold tracking-tight text-white">Engineered for Technical Excellence</h2>
          <p className="text-zinc-400">Everything you need to master DSA, System Design, and SQL interviews in one unified workspace.</p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <Card variant="interactive" className="space-y-4">
            <div className="w-10 h-10 rounded-lg bg-cyan-500/10 border border-cyan-500/20 flex items-center justify-center text-cyan-400">
              <Brain size={20} />
            </div>
            <h3 className="text-lg font-semibold text-white">AI Doubt Solver</h3>
            <p className="text-sm text-zinc-400 leading-relaxed">
              Stuck on a problem? Ask the AI assistant for hints, optimal space/time complexity breakdowns, or edge-case walkthroughs without spoiling solutions.
            </p>
          </Card>

          <Card variant="interactive" className="space-y-4">
            <div className="w-10 h-10 rounded-lg bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center text-indigo-400">
              <BookOpen size={20} />
            </div>
            <h3 className="text-lg font-semibold text-white">Interactive Courses</h3>
            <p className="text-sm text-zinc-400 leading-relaxed">
              Step-by-step System Design tracks covering Load Balancing, Consistent Hashing, Rate Limiters, and Database Sharding with SQL playgrounds.
            </p>
          </Card>

          <Card variant="interactive" className="space-y-4">
            <div className="w-10 h-10 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400">
              <CheckCircle2 size={20} />
            </div>
            <h3 className="text-lg font-semibold text-white">Structured Practice</h3>
            <p className="text-sm text-zinc-400 leading-relaxed">
              Categorized question bank of 1080+ problems filtered by top tech companies (Google, Amazon, Meta, Apple) and difficulty.
            </p>
          </Card>
        </div>
      </section>

      {/* Footer */}
      <footer className="relative z-10 max-w-7xl mx-auto px-6 py-8 border-t border-zinc-900 text-center text-xs text-zinc-500">
        <p>© 2026 Interview Assistant. Production Technical Practice Platform.</p>
      </footer>
    </div>
  );
}
