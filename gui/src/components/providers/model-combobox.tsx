"use client";

import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ModelInfo } from "@/lib/types";

interface ModelComboBoxProps {
  value: string;
  onChange: (id: string) => void;
  options: ModelInfo[];
  placeholder?: string;
  groupByLab?: boolean;
  disabled?: boolean;
  maxVisible?: number;
  inputId?: string;
}

const DEFAULT_MAX_VISIBLE = 100;

function matchModel(m: ModelInfo, query: string): boolean {
  if (!query) return true;
  const q = query.toLowerCase();
  if (m.id.toLowerCase().includes(q)) return true;
  if (m.name.toLowerCase().includes(q)) return true;
  if (m.lab.toLowerCase().includes(q)) return true;
  return m.tags.some((t) => t.toLowerCase().includes(q));
}

export function ModelComboBox({
  value,
  onChange,
  options,
  placeholder = "Search models...",
  groupByLab = true,
  disabled = false,
  maxVisible = DEFAULT_MAX_VISIBLE,
  inputId,
}: ModelComboBoxProps) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [activeIdx, setActiveIdx] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const generatedId = useId();
  const fieldId = inputId ?? generatedId;

  const selected = useMemo(
    () => options.find((o) => o.id === value) ?? null,
    [options, value],
  );

  const filtered = useMemo(() => {
    if (!query) return options;
    return options.filter((m) => matchModel(m, query));
  }, [options, query]);

  const grouped = useMemo(() => {
    if (!groupByLab) return null;
    const capped = filtered.slice(0, maxVisible);
    const groups = new Map<string, ModelInfo[]>();
    for (const m of capped) {
      const arr = groups.get(m.lab) ?? [];
      arr.push(m);
      groups.set(m.lab, arr);
    }
    return Array.from(groups.entries()).sort(([a], [b]) => a.localeCompare(b));
  }, [filtered, maxVisible, groupByLab]);

  // visible is the flat render-order list. Keyboard navigation indexes into it,
  // so it MUST match the order in which renderRow is called (grouped order when
  // groupByLab is true).
  const visible = useMemo(() => {
    if (grouped) return grouped.flatMap(([, models]) => models);
    return filtered.slice(0, maxVisible);
  }, [filtered, grouped, maxVisible]);

  useEffect(() => {
    if (activeIdx >= visible.length) setActiveIdx(0);
  }, [visible.length, activeIdx]);

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (!containerRef.current?.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    if (open) document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  const handleSelect = useCallback(
    (m: ModelInfo) => {
      onChange(m.id);
      setQuery("");
      setOpen(false);
    },
    [onChange],
  );

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(true);
      setActiveIdx((i) => Math.min(i + 1, visible.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      if (open && visible[activeIdx]) {
        e.preventDefault();
        handleSelect(visible[activeIdx]);
      }
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  const displayValue = open ? query : selected?.id ?? query;

  let runningIdx = -1;
  const renderRow = (m: ModelInfo) => {
    runningIdx += 1;
    const idx = runningIdx;
    const isActive = idx === activeIdx;
    const isSelected = m.id === value;
    return (
      <li
        key={m.id}
        role="option"
        aria-selected={isSelected}
        onMouseDown={(e) => {
          e.preventDefault();
          handleSelect(m);
        }}
        onMouseEnter={() => setActiveIdx(idx)}
        className={
          "px-3 py-2 cursor-pointer text-sm flex items-baseline justify-between gap-3 " +
          (isActive ? "bg-primary/10 " : "") +
          (isSelected ? "font-medium " : "")
        }
      >
        <div className="min-w-0 flex-1">
          <div className="font-mono text-xs truncate text-primary-text">
            {m.id}
          </div>
          {m.name && m.name !== m.id ? (
            <div className="text-[11px] text-muted truncate">{m.name}</div>
          ) : null}
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {m.context_window > 0 ? (
            <span className="text-[10px] text-muted whitespace-nowrap">
              {Math.round(m.context_window / 1000)}k
            </span>
          ) : null}
          {m.tags.slice(0, 2).map((t) => (
            <span
              key={t}
              className="text-[10px] px-1.5 py-0.5 rounded bg-panel text-secondary whitespace-nowrap"
            >
              {t}
            </span>
          ))}
        </div>
      </li>
    );
  };

  return (
    <div ref={containerRef} className="relative">
      <input
        id={fieldId}
        type="text"
        role="combobox"
        aria-expanded={open}
        aria-controls={`${fieldId}-listbox`}
        aria-autocomplete="list"
        value={displayValue}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
          setActiveIdx(0);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        disabled={disabled}
        autoComplete="off"
        className="w-full px-3 py-2 text-sm border border-default rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary font-mono"
      />
      {open && !disabled ? (
        <ul
          ref={listRef}
          id={`${fieldId}-listbox`}
          role="listbox"
          className="absolute z-50 mt-1 w-full max-h-72 overflow-auto bg-white border border-default rounded-lg shadow-lg"
        >
          {visible.length === 0 ? (
            <li className="px-3 py-2 text-xs text-muted">No models match</li>
          ) : grouped ? (
            grouped.map(([lab, models]) => (
              <li key={lab} className="py-1">
                <div className="px-3 py-1 text-[10px] uppercase tracking-wide text-muted font-semibold bg-panel">
                  {lab}
                </div>
                <ul role="group">{models.map(renderRow)}</ul>
              </li>
            ))
          ) : (
            visible.map(renderRow)
          )}
          {filtered.length > visible.length ? (
            <li className="px-3 py-1 text-[10px] text-muted border-t border-default">
              Showing {visible.length} of {filtered.length} — refine search to
              see more
            </li>
          ) : null}
        </ul>
      ) : null}
    </div>
  );
}
