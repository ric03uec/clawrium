import type { Metadata } from "next";
import "@/styles/globals.css";
import "@/design-system/styles.css";
import { Providers } from "./providers";
import { AppShell } from "@/components/layout";

// Removed `next/font/google` Inter import: it forced a build-time fetch
// of `fonts.googleapis.com` which intermittently failed in CI (DNS
// ENOTFOUND on the macOS runner). The design-system `--font-sans` token
// includes the full offline-safe system-font fallback chain, so dropping
// hosted Inter falls through to the platform's native UI font.

export const metadata: Metadata = {
  title: "Clawrium",
  description: "AI assistant fleet management dashboard",
  icons: {
    icon: "/clawrium-logo.png",
    shortcut: "/clawrium-logo.png",
    apple: "/clawrium-logo.png",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="iteration-design-system">
        <Providers>
          <AppShell>{children}</AppShell>
        </Providers>
      </body>
    </html>
  );
}
