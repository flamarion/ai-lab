"use client";

import { useCallback, useRef } from "react";

interface Props {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  rows?: number;
  className?: string;
}

/**
 * Lightweight JSON editor textarea with:
 * - Tab key inserts 2 spaces (instead of moving focus)
 * - Shift+Tab removes 2 spaces of indentation
 * - Auto-formats JSON on paste
 * - Format button for manual cleanup
 * - Enter auto-indents to match the previous line
 */
export default function JsonEditor({ value, onChange, placeholder, rows = 8, className = "" }: Props) {
  const ref = useRef<HTMLTextAreaElement>(null);

  const formatJson = useCallback(() => {
    try {
      const parsed = JSON.parse(value);
      onChange(JSON.stringify(parsed, null, 2));
    } catch {
      // Not valid JSON — leave as-is
    }
  }, [value, onChange]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      const textarea = e.currentTarget;
      const { selectionStart, selectionEnd } = textarea;

      // Tab → insert 2 spaces
      if (e.key === "Tab" && !e.shiftKey) {
        e.preventDefault();
        const before = value.slice(0, selectionStart);
        const after = value.slice(selectionEnd);
        const newValue = before + "  " + after;
        onChange(newValue);
        // Restore cursor position after React re-renders
        requestAnimationFrame(() => {
          textarea.selectionStart = textarea.selectionEnd = selectionStart + 2;
        });
      }

      // Shift+Tab → remove 2 spaces of indentation
      if (e.key === "Tab" && e.shiftKey) {
        e.preventDefault();
        const lineStart = value.lastIndexOf("\n", selectionStart - 1) + 1;
        const linePrefix = value.slice(lineStart, selectionStart);
        if (linePrefix.startsWith("  ")) {
          const newValue = value.slice(0, lineStart) + value.slice(lineStart + 2);
          onChange(newValue);
          requestAnimationFrame(() => {
            textarea.selectionStart = textarea.selectionEnd = Math.max(selectionStart - 2, lineStart);
          });
        }
      }

      // Enter → auto-indent to match previous line
      if (e.key === "Enter") {
        e.preventDefault();
        const before = value.slice(0, selectionStart);
        const after = value.slice(selectionEnd);
        // Find indentation of current line
        const lineStart = before.lastIndexOf("\n") + 1;
        const currentLine = before.slice(lineStart);
        const indent = currentLine.match(/^(\s*)/)?.[1] || "";
        // Add extra indent after { or [
        const lastChar = before.trimEnd().slice(-1);
        const extraIndent = lastChar === "{" || lastChar === "[" ? "  " : "";
        const newValue = before + "\n" + indent + extraIndent + after;
        onChange(newValue);
        requestAnimationFrame(() => {
          const pos = selectionStart + 1 + indent.length + extraIndent.length;
          textarea.selectionStart = textarea.selectionEnd = pos;
        });
      }
    },
    [value, onChange]
  );

  const handlePaste = useCallback(
    (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
      const pasted = e.clipboardData.getData("text");
      // Try to auto-format if the paste looks like JSON
      try {
        const parsed = JSON.parse(pasted);
        e.preventDefault();
        const formatted = JSON.stringify(parsed, null, 2);
        const textarea = e.currentTarget;
        const before = value.slice(0, textarea.selectionStart);
        const after = value.slice(textarea.selectionEnd);
        onChange(before + formatted + after);
      } catch {
        // Not valid JSON — let the default paste happen
      }
    },
    [value, onChange]
  );

  const isValid = (() => {
    if (!value.trim()) return null; // empty = neutral
    try {
      JSON.parse(value);
      return true;
    } catch {
      return false;
    }
  })();

  return (
    <div className="relative">
      <textarea
        ref={ref}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        onPaste={handlePaste}
        placeholder={placeholder}
        rows={rows}
        spellCheck={false}
        className={`w-full px-3 py-2 rounded-lg bg-[var(--color-bg)] border text-sm font-[var(--font-mono)] text-[var(--color-text)] focus:outline-none resize-y leading-relaxed ${
          isValid === false
            ? "border-[var(--color-error)]/50 focus:border-[var(--color-error)]"
            : isValid === true
              ? "border-[var(--color-border)] focus:border-[var(--color-accent)]"
              : "border-[var(--color-border)] focus:border-[var(--color-accent)]"
        } ${className}`}
      />
      <div className="absolute top-1.5 right-1.5 flex items-center gap-1">
        {isValid === false && (
          <span className="text-[10px] text-[var(--color-error)] bg-[var(--color-bg)] px-1.5 py-0.5 rounded">
            Invalid JSON
          </span>
        )}
        {isValid === true && (
          <button
            onClick={formatJson}
            type="button"
            className="text-[10px] text-[var(--color-text-muted)] hover:text-[var(--color-accent)] bg-[var(--color-bg)] px-1.5 py-0.5 rounded transition-colors"
          >
            Format
          </button>
        )}
      </div>
    </div>
  );
}
