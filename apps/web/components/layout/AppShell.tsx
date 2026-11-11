"use client";

import { useEffect, useState } from "react";
import { Logo, Sidebar, type SidebarUser } from "./Sidebar";

/**
 * From the tablet breakpoint up the navigation is a fixed column beside the page. Below it the column is
 * hidden behind a menu button in a top bar, and opens over the page: a hidden menu is display:none, so it
 * is out of the tab order until it is opened.
 */
export function AppShell({ user, children }: { user: SidebarUser; children: React.ReactNode }) {
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    if (!menuOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMenuOpen(false);
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [menuOpen]);

  return (
    <div className="flex h-dvh flex-col overflow-hidden md:flex-row">
      <header className="flex h-14 shrink-0 items-center justify-between border-b px-4 md:hidden" style={{ background: "var(--surface)", borderColor: "var(--border)" }}>
        <Logo />
        <button
          type="button"
          aria-label={menuOpen ? "Close navigation" : "Open navigation"}
          aria-expanded={menuOpen}
          aria-controls="app-navigation"
          onClick={() => setMenuOpen((open) => !open)}
          className="rounded-md p-2 focus-visible:ring-2 focus-visible:ring-primary"
          style={{ color: "var(--text)" }}
        >
          <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.75} aria-hidden="true">
            {menuOpen ? <path strokeLinecap="round" strokeLinejoin="round" d="M6 6l12 12M18 6L6 18" /> : <path strokeLinecap="round" strokeLinejoin="round" d="M4 7h16M4 12h16M4 17h16" />}
          </svg>
        </button>
      </header>

      {menuOpen && <div className="fixed inset-0 z-30 bg-black/60 md:hidden" aria-hidden="true" onClick={() => setMenuOpen(false)} />}
      <Sidebar user={user} open={menuOpen} onNavigate={() => setMenuOpen(false)} />

      <main className="min-w-0 flex-1 overflow-y-auto">{children}</main>
    </div>
  );
}
