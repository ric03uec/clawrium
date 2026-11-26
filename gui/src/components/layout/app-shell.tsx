"use client";

import { useEffect, useState } from "react";
import { DocumentationButton, RequestFeatureButton } from "./external-links";
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
      <a
        className="skip-link"
        href="#main-content"
        onClick={() => document.getElementById("main-content")?.focus()}
      >
        Skip to main content
      </a>
      <Sidebar version={version} />
      <div className="app-main">
        <header className="app-header" aria-label="Application header">
          <div className="app-header-context">
            <strong>Fleet workspace</strong>
            <span className="app-header-description">Manage agents across your network</span>
          </div>
          <div className="app-header-actions">
            <DocumentationButton />
            <RequestFeatureButton />
          </div>
        </header>
        <main id="main-content" tabIndex={-1} className="app-page ds-grid-backdrop">{children}</main>
        <footer className="app-footer">
          {version && <span>v{version}</span>}
          <a href="https://ric03uec.github.io/clawrium/" target="_blank" rel="noreferrer">Documentation</a>
        </footer>
      </div>
    </div>
  );
}
