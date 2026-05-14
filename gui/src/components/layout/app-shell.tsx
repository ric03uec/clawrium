"use client";

import { Sidebar } from "./sidebar";

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-page">
      <Sidebar />
      <main className="ml-sidebar min-h-screen">
        <div className="p-8">{children}</div>
      </main>
    </div>
  );
}
