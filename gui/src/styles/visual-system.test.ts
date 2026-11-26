import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const readGuiFile = (path: string) => readFileSync(join(process.cwd(), path), "utf8");

function hexToken(styles: string, token: string): string {
  const value = styles.match(new RegExp(`${token}:\\s*(#[0-9a-fA-F]{3,6})`))?.[1];
  if (!value) throw new Error(`Missing hex token ${token}`);
  return value;
}

function contrastRatio(foreground: string, background: string): number {
  const luminance = (hex: string) => {
    const expanded = hex.length === 4
      ? `#${hex.slice(1).split("").map((part) => part + part).join("")}`
      : hex;
    const channels = [1, 3, 5].map((offset) => parseInt(expanded.slice(offset, offset + 2), 16) / 255);
    const linear = channels.map((channel) => channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4);
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
  };
  const lighter = Math.max(luminance(foreground), luminance(background));
  const darker = Math.min(luminance(foreground), luminance(background));
  return (lighter + 0.05) / (darker + 0.05);
}

describe("visual-system activation contracts", () => {
  it("imports the design-system stylesheet exactly once from the root layout", () => {
    const layout = readGuiFile("src/app/layout.tsx");
    expect(layout.match(/import "@\/design-system\/styles\.css";/g)).toHaveLength(1);
    expect(layout).toContain('<body className="iteration-design-system">');
  });

  it("keeps the required shell dimensions and responsive collapsed behavior", () => {
    const globals = readGuiFile("src/styles/globals.css");
    const styles = readGuiFile("src/design-system/styles.css");
    expect(globals).toMatch(/grid-template-columns:\s*248px minmax\(0, 1fr\)/);
    expect(globals).toMatch(/\.app-header\s*\{[^}]*height:\s*72px/s);
    expect(globals).toMatch(/\.app-root:has\(\.ds-app-sidebar\[data-collapsed="true"\]\)\s*\{[^}]*grid-template-columns:\s*72px minmax\(0, 1fr\)/s);
    expect(styles).toMatch(/\.ds-app-sidebar-brand\s*\{[^}]*height:\s*72px/s);
    expect(styles).toMatch(/\.ds-app-sidebar\.sidebar-collapsed \.ds-app-sidebar-card-text[^{]*\{\s*display:\s*none/s);
    expect(styles).toContain("@media (max-width: 600px)");
    expect(styles).toMatch(/\.ds-app-sidebar\.sidebar-collapsed\s*\{[^}]*flex-direction:\s*row/s);
    expect(styles).toMatch(/\.ds-app-sidebar-footer\s*\{[^}]*border-top:\s*1px solid var\(--border\)/s);
    expect(globals).toMatch(/\.app-page\s*\{[^}]*padding:\s*2rem/s);
  });

  it("uses canonical design tokens, grid styling, and focus-visible treatment", () => {
    const styles = readGuiFile("src/design-system/styles.css");
    const globals = readGuiFile("src/styles/globals.css");
    const tailwind = readGuiFile("tailwind.config.ts");

    for (const token of [
      "--primary",
      "--border",
      "--surface-card",
      "--font-sans",
      "--radius",
      "--shadow-card",
      "--focus-ring",
    ]) {
      expect(styles).toContain(token);
    }
    expect(styles).toContain(".ds-grid-backdrop");
    expect(styles).toContain("background-size: 48px 48px");
    const rootRule = styles.match(/\.iteration-design-system\s*\{([^}]*)\}/)?.[1] ?? "";
    expect(rootRule).not.toContain("padding:");
    expect(globals).toContain(":focus-visible");
    expect(globals).toContain("var(--focus-ring)");
    expect(tailwind).toContain('DEFAULT: "var(--primary)"');
    expect(tailwind).toContain('default: "var(--border)"');
    expect(tailwind).not.toMatch(/teal:\s*\{/);
  });

  it("keeps normal primary, success, and warning text at WCAG AA contrast on light surfaces", () => {
    const styles = readGuiFile("src/design-system/styles.css");
    for (const token of ["--primary-text-color", "--success-text", "--warning-text"]) {
      expect(contrastRatio(hexToken(styles, token), "#ffffff"), token).toBeGreaterThanOrEqual(4.5);
    }
    expect(hexToken(styles, "--primary-text-color")).not.toBe(hexToken(styles, "--blue-500"));
    expect(hexToken(styles, "--success-text")).not.toBe(hexToken(styles, "--success"));
  });
});
