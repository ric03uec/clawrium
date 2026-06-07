import type { Metadata } from "next";
import "@/styles/globals.css";
import { Providers } from "./providers";
import { AppShell } from "@/components/layout";

// Removed `next/font/google` Inter import: it forced a build-time fetch
// of `fonts.googleapis.com` which intermittently failed in CI (DNS
// ENOTFOUND on the macOS runner). The body font stack in
// `styles/globals.css` already includes the full system-font fallback
// chain (`-apple-system`, `BlinkMacSystemFont`, ...), so dropping the
// hosted Inter just falls through to the platform's native UI font.

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
      <body>
        <Providers>
          <AppShell>{children}</AppShell>
        </Providers>
      </body>
    </html>
  );
}
