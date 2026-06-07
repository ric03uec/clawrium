"use client";

import { useState } from "react";
import { Button } from "@/components/ui";
import type { SkillCreateInput } from "@/lib/types";

interface SkillCreateFormProps {
  onSubmit: (input: SkillCreateInput) => void;
  isPending: boolean;
  serverError: string | null;
  onCancel: () => void;
}

const NAME_RE = /^[a-z0-9][a-z0-9_-]*$/;

export function SkillCreateForm({
  onSubmit,
  isPending,
  serverError,
  onCancel,
}: SkillCreateFormProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [body, setBody] = useState("");
  const [version, setVersion] = useState("");
  const [author, setAuthor] = useState("");
  const [clientError, setClientError] = useState<string | null>(null);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setClientError(null);
    if (!NAME_RE.test(name)) {
      setClientError(
        "Name must match ^[a-z0-9][a-z0-9_-]*$ (lowercase, digits, _, -)."
      );
      return;
    }
    if (!description.trim()) {
      setClientError("Description is required.");
      return;
    }
    const input: SkillCreateInput = {
      name,
      description: description.trim(),
      body,
    };
    if (version.trim()) input.version = version.trim();
    if (author.trim()) input.author = author.trim();
    onSubmit(input);
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <div>
        <label
          htmlFor="skill-name"
          className="block text-xs font-medium text-primary-text mb-1"
        >
          Name <span className="text-status-warning">*</span>
        </label>
        <input
          id="skill-name"
          type="text"
          required
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="my-skill"
          aria-describedby="skill-name-hint"
          className="w-full text-sm border border-default rounded px-2 py-1.5 bg-surface text-primary-text"
        />
        <p id="skill-name-hint" className="mt-1 text-xs text-muted">
          Lowercase letters, digits, _, -. Cannot be changed later.
        </p>
      </div>

      <div>
        <label
          htmlFor="skill-description"
          className="block text-xs font-medium text-primary-text mb-1"
        >
          Description <span className="text-status-warning">*</span>
        </label>
        <input
          id="skill-description"
          type="text"
          required
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="One-line description"
          className="w-full text-sm border border-default rounded px-2 py-1.5 bg-surface text-primary-text"
        />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label
            htmlFor="skill-version"
            className="block text-xs font-medium text-primary-text mb-1"
          >
            Version
          </label>
          <input
            id="skill-version"
            type="text"
            value={version}
            onChange={(e) => setVersion(e.target.value)}
            placeholder="0.1.0"
            className="w-full text-sm border border-default rounded px-2 py-1.5 bg-surface text-primary-text"
          />
        </div>
        <div>
          <label
            htmlFor="skill-author"
            className="block text-xs font-medium text-primary-text mb-1"
          >
            Author
          </label>
          <input
            id="skill-author"
            type="text"
            value={author}
            onChange={(e) => setAuthor(e.target.value)}
            placeholder="you@example.com"
            className="w-full text-sm border border-default rounded px-2 py-1.5 bg-surface text-primary-text"
          />
        </div>
      </div>

      <div>
        <label
          htmlFor="skill-body"
          className="block text-xs font-medium text-primary-text mb-1"
        >
          SKILL.md body
        </label>
        <textarea
          id="skill-body"
          value={body}
          onChange={(e) => setBody(e.target.value)}
          placeholder={"# Heading\n\nSkill instructions in markdown..."}
          rows={8}
          className="w-full text-xs font-mono border border-default rounded px-2 py-1.5 bg-surface text-primary-text"
        />
      </div>

      {clientError ? (
        <p role="alert" className="text-xs text-status-warning">
          {clientError}
        </p>
      ) : null}
      {serverError ? (
        <p role="alert" className="text-xs text-status-warning">
          {serverError}
        </p>
      ) : null}

      <div className="flex justify-end gap-2 pt-2">
        <Button size="sm" variant="ghost" onClick={onCancel} type="button">
          Cancel
        </Button>
        <Button size="sm" type="submit" disabled={isPending}>
          {isPending ? "Creating…" : "Create"}
        </Button>
      </div>
    </form>
  );
}
