import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const PROJECT_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const SKILL_NAME_PATTERN = /^itx-[a-z0-9-]+$/;

export function discoverItxSkills(
  skillsDirectory = join(PROJECT_ROOT, ".claude", "skills"),
) {
  return readdirSync(skillsDirectory, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && entry.name.startsWith("itx-"))
    .map((entry) => {
      const skillFile = join(skillsDirectory, entry.name, "SKILL.md");
      const source = readFileSync(skillFile, "utf8");
      const name = source.match(/^name:\s*([^\s]+)\s*$/m)?.[1];

      if (!name || !SKILL_NAME_PATTERN.test(name) || name !== entry.name) {
        throw new Error(`Invalid canonical ITX skill: ${skillFile}`);
      }

      return name;
    })
    .sort();
}

export default function registerItxCommandAliases(pi) {
  for (const name of discoverItxSkills()) {
    pi.registerCommand(name, {
      description: `Run the canonical ${name} workflow`,
      handler: async (args) => {
        const suffix = args ? ` ${args}` : "";
        pi.sendUserMessage(`/skill:${name}${suffix}`, {
          deliverAs: "followUp",
          expandPromptTemplates: true,
        });
      },
    });
  }
}
