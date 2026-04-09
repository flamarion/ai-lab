"use client";

import { type ToolUsed, type FileAttachment } from "@/lib/api";
import { Wrench, ListChecks, ChevronDown, ChevronUp, Copy, Check } from "lucide-react";
import FileIcon from "@/components/file-icon";
import { useState, useCallback, lazy, Suspense } from "react";
import ReactMarkdown from "react-markdown";
import { Eye, Code } from "lucide-react";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";

const HtmlPreview = lazy(() => import("@/components/html-preview"));

interface Props {
  role: "user" | "assistant";
  content: string;
  images?: string[];
  attachments?: FileAttachment[];
  toolsUsed?: ToolUsed[];
  plan?: string;
  statusText?: string;
  isStreaming?: boolean;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function CodeBlock({ className, children }: { className?: string; children: React.ReactNode }) {
  const [copied, setCopied] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const text = String(children).replace(/\n$/, "");
  const lang = className?.replace("language-", "") || "";
  const isHtml = lang === "html";

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [text]);

  return (
    <div className="relative group my-3">
      {lang && (
        <div className="flex items-center justify-between px-4 py-1.5 bg-[var(--color-bg)] border border-b-0 border-[var(--color-border)] rounded-t-lg">
          <span className="text-xs text-[var(--color-text-muted)]">{lang}</span>
          <div className="flex items-center gap-3">
            {isHtml && (
              <button
                onClick={() => setPreviewing((p) => !p)}
                className="text-xs text-[var(--color-text-muted)] hover:text-[var(--color-accent)] flex items-center gap-1 transition-colors"
              >
                {previewing ? <Code size={12} /> : <Eye size={12} />}
                {previewing ? "Code" : "Preview"}
              </button>
            )}
            <button
              onClick={handleCopy}
              className="text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text)] flex items-center gap-1 transition-colors"
            >
              {copied ? <Check size={12} /> : <Copy size={12} />}
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
        </div>
      )}
      {previewing && isHtml ? (
        <Suspense fallback={<div className="p-4 text-sm text-[var(--color-text-muted)]">Loading preview...</div>}>
          <HtmlPreview content={text} />
        </Suspense>
      ) : (
        <pre className={`bg-[var(--color-bg-tertiary)] border border-[var(--color-border)] p-4 overflow-x-auto text-sm ${lang ? "rounded-b-lg" : "rounded-lg"}`}>
          <code className={`font-[var(--font-mono)] ${className || ""}`}>{text}</code>
        </pre>
      )}
      {!lang && (
        <button
          onClick={handleCopy}
          className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text)] p-1 rounded transition-opacity"
        >
          {copied ? <Check size={12} /> : <Copy size={12} />}
        </button>
      )}
    </div>
  );
}

/** Build a displayable src for an image string. Data URLs pass through; raw base64 gets a MIME prefix. */
function toImageSrc(img: string): string {
  if (img.startsWith("data:")) return img;
  // Detect format from base64 magic bytes
  if (img.startsWith("iVBOR")) return `data:image/png;base64,${img}`;
  if (img.startsWith("R0lG")) return `data:image/gif;base64,${img}`;
  if (img.startsWith("UklGR")) return `data:image/webp;base64,${img}`;
  return `data:image/jpeg;base64,${img}`;
}

export default function ChatMessage({ role, content, images, attachments, toolsUsed, plan, isStreaming, statusText }: Props) {
  const [toolsOpen, setToolsOpen] = useState(false);
  const [planOpen, setPlanOpen] = useState(false);
  const [expandedImage, setExpandedImage] = useState<string | null>(null);

  return (
    <div className={`animate-fade-in ${role === "user" ? "flex justify-end" : ""}`}>
      <div
        className={`max-w-2xl ${
          role === "user"
            ? "bg-[var(--color-user-bubble)] rounded-2xl rounded-br-md px-4 py-3"
            : "py-3"
        }`}
      >
        {/* Agent plan indicator */}
        {plan && (
          <div className="mb-3">
            <button
              onClick={() => setPlanOpen(!planOpen)}
              className="flex items-center gap-2 text-xs text-[var(--color-text-secondary)] hover:text-[var(--color-text)] transition-colors"
            >
              <ListChecks size={12} />
              Plan
              {planOpen ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            </button>
            {planOpen && (
              <div className="mt-2 animate-fade-in bg-[var(--color-bg-tertiary)] rounded-lg p-3 text-xs border border-[var(--color-border)]">
                <pre className="text-[var(--color-text-secondary)] whitespace-pre-wrap font-[var(--font-mono)]">{plan}</pre>
              </div>
            )}
          </div>
        )}

        {/* Tool usage indicator */}
        {toolsUsed && toolsUsed.length > 0 && (
          <div className="mb-3">
            <button
              onClick={() => setToolsOpen(!toolsOpen)}
              className="flex items-center gap-2 text-xs text-[var(--color-accent)] hover:text-[var(--color-accent-hover)] transition-colors"
            >
              <Wrench size={12} />
              Used {toolsUsed.length} tool{toolsUsed.length > 1 ? "s" : ""}
              {toolsOpen ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            </button>
            {toolsOpen && (
              <div className="mt-2 space-y-2 animate-fade-in">
                {toolsUsed.map((t, i) => (
                  <div key={i} className="bg-[var(--color-bg-tertiary)] rounded-lg p-3 text-xs border border-[var(--color-border)]">
                    <div className="font-medium text-[var(--color-accent)] mb-1">
                      {t.name}({Object.entries(t.arguments).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(", ")})
                    </div>
                    <pre className="text-[var(--color-text-secondary)] whitespace-pre-wrap font-[var(--font-mono)] overflow-x-auto">
                      {t.result.slice(0, 500)}{t.result.length > 500 ? "..." : ""}
                    </pre>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Attached images */}
        {images && images.length > 0 && (
          <div className="flex gap-2 flex-wrap mb-2">
            {images.map((img, i) => (
              <button key={i} onClick={() => setExpandedImage(img)} className="block">
                <img
                  src={toImageSrc(img)}
                  alt={`Attachment ${i + 1}`}
                  className="max-h-48 max-w-64 rounded-lg border border-[var(--color-border)] object-contain cursor-pointer hover:opacity-90 transition-opacity"
                />
              </button>
            ))}
          </div>
        )}

        {/* File attachments */}
        {attachments && attachments.length > 0 && (
          <div className="flex gap-2 flex-wrap mb-2">
            {attachments.map((att, i) => (
              <div key={i} className="flex items-center gap-1.5 bg-[var(--color-bg-tertiary)] border border-[var(--color-border)] rounded-lg px-2.5 py-1.5">
                <FileIcon name={att.name} size={14} />
                <span className="text-xs text-[var(--color-text-secondary)] max-w-40 truncate">{att.name}</span>
                {att.size > 0 && (
                  <span className="text-xs text-[var(--color-text-muted)]">{formatSize(att.size)}</span>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Expanded image overlay */}
        {expandedImage && (
          <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 cursor-pointer"
            onClick={() => setExpandedImage(null)}
          >
            <img
              src={toImageSrc(expandedImage)}
              alt="Expanded view"
              className="max-h-[90vh] max-w-[90vw] rounded-lg object-contain"
            />
          </div>
        )}

        {/* Message content — rendered as markdown for both user and assistant */}
        <div className="message-content text-[0.9375rem] leading-relaxed [&>:last-child]:mb-0">
          <ReactMarkdown
            remarkPlugins={[remarkGfm, remarkBreaks]}
            components={{
              code({ className, children, ...props }) {
                const isBlock = className || String(children).includes("\n");
                if (isBlock) {
                  return <CodeBlock className={className}>{children}</CodeBlock>;
                }
                return (
                  <code className="font-[var(--font-mono)] text-[0.85em] bg-[var(--color-bg-tertiary)] px-1.5 py-0.5 rounded" {...props}>
                    {children}
                  </code>
                );
              },
              pre({ children }) {
                return <>{children}</>;
              },
              // Block images to prevent external request tracking
              img({ alt }) {
                return <span className="text-[var(--color-text-muted)] italic">[image: {alt || "removed"}]</span>;
              },
              table({ children }) {
                return (
                  <div className="overflow-x-auto my-3">
                    <table className="w-full text-sm border-collapse border border-[var(--color-border)]">
                      {children}
                    </table>
                  </div>
                );
              },
              th({ children }) {
                return (
                  <th className="border border-[var(--color-border)] px-3 py-2 bg-[var(--color-bg-secondary)] text-left font-medium">
                    {children}
                  </th>
                );
              },
              td({ children }) {
                return (
                  <td className="border border-[var(--color-border)] px-3 py-2">
                    {children}
                  </td>
                );
              },
              a({ href, children }) {
                return (
                  <a href={href} target="_blank" rel="noopener noreferrer" className="text-[var(--color-accent)] underline underline-offset-2 hover:text-[var(--color-accent-hover)]">
                    {children}
                  </a>
                );
              },
            }}
          >
            {content}
          </ReactMarkdown>
        </div>

        {/* Streaming indicator */}
        {isStreaming && !content && (
          <div className="flex items-center gap-2 mt-2">
            <span className="typing-dot w-1.5 h-1.5 rounded-full bg-[var(--color-text-muted)]" />
            <span className="typing-dot w-1.5 h-1.5 rounded-full bg-[var(--color-text-muted)]" />
            <span className="typing-dot w-1.5 h-1.5 rounded-full bg-[var(--color-text-muted)]" />
            {statusText && (
              <span className="text-xs text-[var(--color-text-muted)] ml-1">{statusText}</span>
            )}
          </div>
        )}
        {/* Blinking cursor while tokens are arriving */}
        {isStreaming && content && (
          <span className="inline-block w-2 h-4 bg-[var(--color-text-muted)] animate-pulse ml-0.5 align-text-bottom" />
        )}
      </div>
    </div>
  );
}
