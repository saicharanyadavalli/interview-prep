"use client";

import React, { useState, useEffect } from "react";
import Link from "next/link";
import Image from "next/image";
import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { UserAvatar } from "@/components/UserAvatar";
import { LayoutDashboard, List, Activity, RotateCcw, User, LogOut, Moon, Sun, Menu, BookOpen, ChevronsLeft, ChevronsRight } from "lucide-react";

export function Sidebar() {
  const pathname = usePathname();
  const { user, signOut, getUserMeta, loading } = useAuth();
  const [theme, setTheme] = useState("dark");
  const [isOpen, setIsOpen] = useState(false);
  const [isCollapsed, setIsCollapsed] = useState(false);

  useEffect(() => {
    const savedTheme = localStorage.getItem("theme") || document.documentElement.getAttribute("data-theme") || "dark";
    setTheme(savedTheme);
    document.documentElement.setAttribute("data-theme", savedTheme);
    document.cookie = `theme=${savedTheme}; path=/; max-age=31536000; SameSite=Lax`;

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
    document.cookie = `theme=${next}; path=/; max-age=31536000; SameSite=Lax`;
  };

  const closeMobile = () => setIsOpen(false);

  const meta = getUserMeta();

  // Do not render sidebar on login page
  if (pathname === "/login" || pathname === "/") {
    return null;
  }

  return (
    <>
      <button 
        className="sidebar-toggle" 
        type="button" 
        aria-label={isOpen ? "Close navigation menu" : "Open navigation menu"}
        aria-expanded={isOpen}
        onClick={() => setIsOpen((prev) => !prev)}
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
            <Link
              href="/dashboard"
              className="sidebar-brand-link"
              onClick={closeMobile}
              aria-label="Interview Assistant Dashboard"
              title="Interview Assistant - Go to Dashboard"
            >
              <Image className="brand-logo" src="/assets/logo-mark.svg" alt="Interview Assistant logo" width={24} height={24} />
              <span className="sidebar-brand-text">Interview Assistant</span>
            </Link>
          </h2>
          <button 
            type="button" 
            className="sidebar-collapse-btn"
            onClick={toggleCollapse}
            aria-label={isCollapsed ? "Expand sidebar" : "Collapse sidebar"}
            aria-expanded={!isCollapsed}
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
          <Link href="/dsa/leetcode" className={`sidebar-link ${pathname.startsWith("/dsa/leetcode") ? "active" : ""}`} onClick={closeMobile} aria-label="LeetCode DSA" title="LeetCode DSA">
            <BookOpen className="nav-icon" size={18} /> <span className="nav-label">LeetCode DSA</span>
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
            <UserAvatar 
              className="sidebar-avatar" 
              src={meta.avatar} 
              name={meta.name}
              username={meta.username}
              size={32}
              alt={`${meta.name || "User"}'s avatar`}
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
              aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
              onClick={toggleTheme}
              title={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
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
