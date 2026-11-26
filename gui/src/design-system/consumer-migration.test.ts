import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";
import ts from "typescript";
import { describe, expect, it } from "vitest";

const root = process.cwd();
const upstreamSha = "6fa5f42a9892c15e4ef41bee9e67dd5826d1ae7f";

function sourceFiles(dir: string): string[] {
  return readdirSync(join(root, dir)).flatMap((entry) => {
    const path = join(dir, entry);
    return statSync(join(root, path)).isDirectory()
      ? sourceFiles(path)
      : /\.tsx?$/.test(path)
        ? [path]
        : [];
  });
}

function isWithin(path: string, directory: string): boolean {
  const offset = relative(directory, path);
  return offset === "" || (!offset.startsWith(`..${sep}`) && offset !== "..");
}

const productionFiles = sourceFiles("src").filter(
  (path) => !path.includes(".test.") && !isWithin(path, "src/design-system"),
);

function parse(path: string): ts.SourceFile {
  return ts.createSourceFile(
    path,
    readFileSync(join(root, path), "utf8"),
    ts.ScriptTarget.Latest,
    true,
    path.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  );
}

function importsFrom(sourceFile: ts.SourceFile, moduleName: string, importName?: string): boolean {
  return sourceFile.statements.some((statement) => {
    if (!ts.isImportDeclaration(statement) || !ts.isStringLiteral(statement.moduleSpecifier)) return false;
    if (statement.moduleSpecifier.text !== moduleName) return false;
    if (!importName) return true;
    const bindings = statement.importClause?.namedBindings;
    return (
      bindings !== undefined &&
      ts.isNamedImports(bindings) &&
      bindings.elements.some((element) => (element.propertyName ?? element.name).text === importName)
    );
  });
}

function jsxElements(sourceFile: ts.SourceFile, tagName: string): Array<ts.JsxOpeningElement | ts.JsxSelfClosingElement> {
  const matches: Array<ts.JsxOpeningElement | ts.JsxSelfClosingElement> = [];
  function visit(node: ts.Node) {
    if (
      (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) &&
      ts.isIdentifier(node.tagName) &&
      node.tagName.text === tagName
    ) {
      matches.push(node);
    }
    ts.forEachChild(node, visit);
  }
  visit(sourceFile);
  return matches;
}

function jsxAttribute(
  element: ts.JsxOpeningElement | ts.JsxSelfClosingElement,
  name: string,
): ts.JsxAttribute | undefined {
  return element.attributes.properties.find(
    (property): property is ts.JsxAttribute => ts.isJsxAttribute(property) && property.name.getText() === name,
  );
}

const requiredPrimitiveFiles = [
  "agent-logo.tsx",
  "app-sidebar.tsx",
  "button.tsx",
  "card.tsx",
  "data-table.tsx",
  "eyebrow.tsx",
  "host-card.tsx",
  "input.tsx",
  "page-header.tsx",
  "stat-block.tsx",
  "status-chip.tsx",
  "status-light.tsx",
  "styles.css",
  "tab-bar.tsx",
  "ui/button.tsx",
  "ui/card.tsx",
  "ui/input.tsx",
  "ui/table.tsx",
] as const;

const requiredExports = [
  "agent-logo",
  "app-sidebar",
  "button",
  "card",
  "data-table",
  "eyebrow",
  "host-card",
  "input",
  "page-header",
  "stat-block",
  "status-chip",
  "status-light",
  "tab-bar",
] as const;

const trackingContracts: Record<string, string> = {
  "agent-logo.tsx": "agent-logo",
  "app-sidebar.tsx": "app-sidebar",
  "button.tsx": "button",
  "card.tsx": "card",
  "data-table.tsx": "data-table",
  "eyebrow.tsx": "eyebrow",
  "host-card.tsx": "host-card",
  "input.tsx": "input",
  "page-header.tsx": "page-header",
  "stat-block.tsx": "stat-block",
  "status-chip.tsx": "status-chip",
  "status-light.tsx": "status-light",
  "tab-bar.tsx": "tab-bar",
};

const pageHeaderFiles = [
  "src/app/agents/page.tsx",
  "src/app/hosts/page.tsx",
  "src/app/integrations/page.tsx",
  "src/app/mcp-servers/page.tsx",
  "src/app/page.tsx",
  "src/app/providers/page.tsx",
  "src/app/settings/page.tsx",
  "src/app/skills/page.tsx",
  "src/app/topology/page.tsx",
] as const;

const listSurfaces = [
  "src/app/integrations/page.tsx",
  "src/components/dashboard/agent-table.tsx",
  "src/components/providers/model-catalog.tsx",
  "src/components/providers/providers-table.tsx",
] as const;

describe("design-system production migration contracts", () => {
  it("pins the copied-once source and keeps the complete public registry", () => {
    const readme = readFileSync(join(root, "src/design-system/README.md"), "utf8");
    expect(readme.match(new RegExp(upstreamSha, "g"))).toHaveLength(1);

    for (const path of requiredPrimitiveFiles) {
      expect(existsSync(join(root, "src/design-system", path)), path).toBe(true);
    }

    const registry = readFileSync(join(root, "src/design-system/index.ts"), "utf8");
    for (const moduleName of requiredExports) {
      expect(registry, moduleName).toContain(`export * from "./${moduleName}";`);
    }
  });

  it("does not acquire an upstream i7n runtime or development dependency", () => {
    const packageJson = JSON.parse(readFileSync(join(root, "package.json"), "utf8")) as {
      dependencies?: Record<string, string>;
      devDependencies?: Record<string, string>;
      optionalDependencies?: Record<string, string>;
      peerDependencies?: Record<string, string>;
    };
    const dependencyNames = Object.keys({
      ...packageJson.dependencies,
      ...packageJson.devDependencies,
      ...packageJson.optionalDependencies,
      ...packageJson.peerDependencies,
    });
    expect(dependencyNames.filter((name) => /(^|[\/@-])i7n([\/@-]|$)/i.test(name))).toEqual([]);
  });

  it("preserves every public primitive tracking contract", () => {
    for (const [path, componentName] of Object.entries(trackingContracts)) {
      const source = readFileSync(join(root, "src/design-system", path), "utf8");
      expect(source, path).toMatch(/trackingId:\s*string/);
      expect(source, path).toContain(`data-i7n-component="${componentName}"`);
      expect(source, path).toContain("data-i7n-name={trackingId}");
    }
  });

  it("removes obsolete local PageHeader, Button, and Card implementations and imports", () => {
    const obsoleteModules = [
      "@/components/layout/page-header",
      "@/components/ui/button",
      "@/components/ui/card",
    ];
    for (const path of [
      "src/components/layout/page-header.tsx",
      "src/components/ui/button.tsx",
      "src/components/ui/card.tsx",
    ]) {
      expect(existsSync(join(root, path)), path).toBe(false);
    }

    for (const path of productionFiles) {
      const sourceFile = parse(path);
      for (const moduleName of obsoleteModules) {
        expect(importsFrom(sourceFile, moduleName), `${path} imports ${moduleName}`).toBe(false);
      }
    }
  });

  it("keeps application sidebar structure and styling centralized in the design system", () => {
    const consumers = productionFiles.filter((path) => importsFrom(parse(path), "@/design-system", "AppSidebar"));
    expect(consumers).toEqual(["src/components/layout/sidebar.tsx"]);

    const adapter = readFileSync(join(root, "src/components/layout/sidebar.tsx"), "utf8");
    const globals = readFileSync(join(root, "src/styles/globals.css"), "utf8");
    expect(adapter).not.toContain("ds-app-sidebar-");
    expect(globals).not.toContain(".ds-app-sidebar-");
  });

  it("requires tracking and meaningful eyebrow copy on every expected production PageHeader", () => {
    const actualFiles = productionFiles
      .filter((path) => jsxElements(parse(path), "PageHeader").length > 0)
      .sort();
    expect(actualFiles).toEqual([...pageHeaderFiles].sort());

    for (const path of pageHeaderFiles) {
      const headers = jsxElements(parse(path), "PageHeader");
      expect(headers, path).toHaveLength(1);
      const trackingId = jsxAttribute(headers[0], "trackingId");
      const eyebrow = jsxAttribute(headers[0], "eyebrow");
      expect(trackingId?.initializer, `${path} trackingId`).toBeDefined();
      expect(eyebrow?.initializer, `${path} eyebrow`).toBeDefined();
      if (eyebrow?.initializer && ts.isStringLiteral(eyebrow.initializer)) {
        expect(eyebrow.initializer.text.trim(), `${path} eyebrow`).not.toBe("");
      }
    }
  });

  it("standardizes every in-scope fleet inventory on DataTable", () => {
    // Skills remains a documented card gallery because each item owns install-specific controls.
    // Hosts and MCP servers are placeholders, not inventories, so neither belongs in this allowlist.
    for (const path of listSurfaces) {
      const sourceFile = parse(path);
      expect(importsFrom(sourceFile, "@/design-system", "DataTable"), `${path} DataTable import`).toBe(true);
      expect(jsxElements(sourceFile, "DataTable"), `${path} DataTable JSX`).not.toHaveLength(0);
    }
  });

  it("leaves only documented specialized raw inputs and no raw application tables", () => {
    // These controls need radio/password/combobox behavior not represented by the text Input primitive.
    const specializedRawInputAllowlist = [
      "components/providers/add-provider-modal.tsx",
      "components/providers/edit-provider-modal.tsx",
      "components/providers/model-combobox.tsx",
    ];
    const rawInputFiles = productionFiles
      .filter((path) => jsxElements(parse(path), "input").length > 0)
      .map((path) => relative("src", path))
      .sort();
    expect(rawInputFiles).toEqual(specializedRawInputAllowlist);

    const rawTableFiles = productionFiles
      .filter((path) => jsxElements(parse(path), "table").length > 0)
      .map((path) => relative("src", path))
      .sort();
    expect(rawTableFiles).toEqual([]);
  });
});
