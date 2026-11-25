"use client";

import { useEffect, useState } from "react";
import { Sidebar } from "./sidebar";

export function AppShell({ children }: { children: React.ReactNode }) {
  const [version, setVersion] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/settings/version", { signal: controller.signal })
      .then((response) => response.json())
      .then((data) => setVersion(data.version || ""))
      .catch(() => {});
    return () => controller.abort();
  }, []);
  return (
    <div className="app-root bg-page">
      <Sidebar version={version} />
      <div className="app-main">
        <header className="app-header" aria-label="Application header" />
        <main className="app-page">{children}</main>
        <footer className="app-footer">
          {version && <span>v{version}</span>}
          <a href="https://github.com/ric03uec/clawrium" target="_blank" rel="noreferrer">GitHub</a>
          <a href="https://ric03uec.github.io/clawrium/" target="_blank" rel="noreferrer">Documentation</a>
        </footer>
      </div>
    </div>
  );
}
