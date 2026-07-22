"use client";

import React, { useState, useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { LayoutDashboard, List, Activity, RotateCcw, User, LogOut, Moon, Sun, Menu, BookOpen, ChevronsLeft, ChevronsRight } from "lucide-react";

function initialsFromName(name: string) {
  const text = String(name || "").trim();
  if (!text) return "U";
  const parts = text.split(/\s+/).filter(Boolean);
  if (parts.length === 1) return parts[0].slice(0, 1).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function buildAvatarDataUri(name: string) {
  const initials = initialsFromName(name);
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96" viewBox="0 0 96 96"><rect width="96" height="96" rx="48" fill="#0f766e"/><text x="48" y="58" text-anchor="middle" font-family="Arial, sans-serif" font-size="36" fill="#ffffff">${initials}</text></svg>`;
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
}

export function Sidebar() {
  const pathname = usePathname();
  const { user, signOut, getUserMeta, loading } = useAuth();
  const [theme, setTheme] = useState("dark");
  const [isOpen, setIsOpen] = useState(false);
  const [isCollapsed, setIsCollapsed] = useState(false);

  useEffect(() => {
    const savedTheme = localStorage.getItem("theme") || "dark";
    setTheme(savedTheme);
    document.documentElement.setAttribute("data-theme", savedTheme);

    const savedCollapsed = localStorage.getItem("sidebarCollapsed") === "true";
    setIsCollapsed(savedCollapsed);
    if (savedCollapsed) {
      document.documentElement.setAttribute("data-sidebar", "collapsed");
    } else {
      document.documentElement.removeAttribute("data-sidebar");
    }

    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'b') {
        e.preventDefault();
        setIsCollapsed(prev => {
          const next = !prev;
          localStorage.setItem("sidebarCollapsed", String(next));
          if (next) {
            document.documentElement.setAttribute("data-sidebar", "collapsed");
          } else {
            document.documentElement.removeAttribute("data-sidebar");
          }
          return next;
        });
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  const toggleCollapse = () => {
    setIsCollapsed(prev => {
      const next = !prev;
      localStorage.setItem("sidebarCollapsed", String(next));
      if (next) {
        document.documentElement.setAttribute("data-sidebar", "collapsed");
      } else {
        document.documentElement.removeAttribute("data-sidebar");
      }
      return next;
    });
  };

  const toggleTheme = () => {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    localStorage.setItem("theme", next);
    document.documentElement.setAttribute("data-theme", next);
  };

  const closeMobile = () => setIsOpen(false);

  const meta = getUserMeta();
  const avatarFallback = buildAvatarDataUri(meta.name);

  // Do not render sidebar on login page
  if (pathname === "/login" || pathname === "/") {
    return null;
  }

  return (
    <>
      <button 
        className="sidebar-toggle" 
        type="button" 
        aria-label="Toggle menu"
        onClick={() => setIsOpen(true)}
      >
        <Menu size={20} />
      </button>
      <div 
        className={`sidebar-overlay ${isOpen ? "open" : ""}`} 
        onClick={() => setIsOpen(false)}
      />
      
      <aside className={`sidebar ${isOpen ? "open" : ""}`}>
        <div className="sidebar-brand" style={{ position: 'relative' }}>
          <h2>
            <img className="brand-logo" src="/assets/logo-mark.svg" alt="Interview Assistant logo" /> 
            <span className="sidebar-brand-text">Interview Assistant</span>
          </h2>
          <button 
            type="button" 
            className="sidebar-collapse-btn"
            onClick={toggleCollapse}
            aria-label={isCollapsed ? "Expand sidebar" : "Collapse sidebar"}
            title={`${isCollapsed ? "Expand" : "Collapse"} sidebar`}
          >
            {isCollapsed ? <ChevronsRight size={14} /> : <ChevronsLeft size={14} />}
          </button>
        </div>
        <nav className="sidebar-nav">
          <Link href="/dashboard" className={`sidebar-link ${pathname === "/dashboard" ? "active" : ""}`} onClick={closeMobile} aria-label="Dashboard" title="Dashboard">
            <LayoutDashboard className="nav-icon" size={18} /> <span className="nav-label">Dashboard</span>
          </Link>
          <Link href="/questions" className={`sidebar-link ${pathname === "/questions" || pathname === "/practice" || pathname === "/solve" ? "active" : ""}`} onClick={closeMobile} aria-label="Questions" title="Questions">
            <List className="nav-icon" size={18} /> <span className="nav-label">Questions</span>
          </Link>
          <Link href="/courses" className={`sidebar-link ${pathname.startsWith("/courses") || pathname.includes("/lessons") || pathname === "/system-design" ? "active" : ""}`} onClick={closeMobile} aria-label="Courses" title="Courses">
            <BookOpen className="nav-icon" size={18} /> <span className="nav-label">Courses</span>
          </Link>
          <Link href="/progress" className={`sidebar-link ${pathname === "/progress" ? "active" : ""}`} onClick={closeMobile} aria-label="Progress" title="Progress">
            <Activity className="nav-icon" size={18} /> <span className="nav-label">Progress</span>
          </Link>
          <Link href="/revisit" className={`sidebar-link ${pathname === "/revisit" ? "active" : ""}`} onClick={closeMobile} aria-label="Revisit" title="Revisit">
            <RotateCcw className="nav-icon" size={18} /> <span className="nav-label">Revisit</span>
          </Link>
          <Link href="/profile" className={`sidebar-link ${pathname === "/profile" ? "active" : ""}`} onClick={closeMobile} aria-label="Profile" title="Profile">
            <User className="nav-icon" size={18} /> <span className="nav-label">Profile</span>
          </Link>
        </nav>
        <div className="sidebar-footer">
          <div className="sidebar-user">
            <img 
              className="sidebar-avatar" 
              src={meta.avatar || avatarFallback} 
              alt="Avatar" 
              onError={(e) => { e.currentTarget.src = avatarFallback; }}
            />
            <div className="sidebar-user-info">
              <p className="sidebar-user-name">{meta.name}</p>
              {meta.username && (
                <p className="sidebar-user-username" style={{ color: "var(--teal)", fontSize: "0.78rem", fontWeight: 600, fontFamily: "monospace", margin: "0.1rem 0" }}>
                  @{meta.username}
                </p>
              )}
              <p className="sidebar-user-email">{meta.email || "Not signed in"}</p>
            </div>
          </div>
          <div className="button-row" style={{ display: 'flex', gap: '0.5rem', padding: '0.5rem' }}>
            <button 
              className="btn btn-sm btn-icon" 
              type="button" 
              aria-label="Toggle theme"
              onClick={toggleTheme}
              title="Toggle Theme"
            >
              {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
            </button>
            {!loading && user ? (
              <button className="btn btn-sm" type="button" onClick={signOut} aria-label="Sign Out" title="Sign Out">
                <LogOut size={16} /> <span className="button-row-text">Sign Out</span>
              </button>
            ) : (
              <Link href="/login" className="btn btn-sm btn-primary" style={{ display: 'inline-flex', alignItems: 'center' }} aria-label="Sign In" title="Sign In">
                <span className="button-row-text">Sign In</span>
              </Link>
            )}
          </div>
        </div>
      </aside>
    </>
  );
}
