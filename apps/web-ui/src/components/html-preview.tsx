"use client";

import { useRef, useEffect, useState } from "react";

// Read Chart.js UMD bundle at build time so it can be injected into sandboxed iframes.
// Using require() with fs is not viable in a client component, so we import the UMD
// bundle as a static asset via a raw string. Next.js will inline this at build time.
const CHART_JS_CDN = "https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js";

const INJECTED_HEAD = `
<script src="${CHART_JS_CDN}"><\/script>
<style>
  * { box-sizing: border-box; }
  body {
    margin: 1rem;
    background: #0f1117;
    color: #e8e6e3;
    font-family: "DM Sans", system-ui, sans-serif;
  }
  canvas { max-width: 100%; }
</style>
<script>
  // Report content height to parent for auto-resize
  const _notifyHeight = () => {
    const h = document.documentElement.scrollHeight;
    window.parent.postMessage({ type: "resize", height: h }, "*");
  };
  window.addEventListener("load", () => setTimeout(_notifyHeight, 100));
  new MutationObserver(_notifyHeight).observe(document.body, { childList: true, subtree: true, attributes: true });
<\/script>
`;

const MAX_HEIGHT = 600;
const DEFAULT_HEIGHT = 400;

interface HtmlPreviewProps {
  content: string;
}

export default function HtmlPreview({ content }: HtmlPreviewProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [height, setHeight] = useState(DEFAULT_HEIGHT);

  useEffect(() => {
    const handler = (e: MessageEvent) => {
      if (
        e.source === iframeRef.current?.contentWindow &&
        e.data?.type === "resize" &&
        typeof e.data.height === "number"
      ) {
        setHeight(Math.min(e.data.height, MAX_HEIGHT));
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, []);

  // Wrap content: if it already has <html> or <head>, inject into <head>;
  // otherwise wrap in a full document.
  const srcDoc = buildSrcDoc(content);

  return (
    <iframe
      ref={iframeRef}
      srcDoc={srcDoc}
      sandbox="allow-scripts"
      style={{
        width: "100%",
        height: `${height}px`,
        border: "1px solid var(--color-border)",
        borderRadius: "0 0 0.5rem 0.5rem",
        background: "#0f1117",
      }}
      title="HTML Preview"
    />
  );
}

function buildSrcDoc(content: string): string {
  const lower = content.toLowerCase();

  // If the content already has a <head>, inject our styles/scripts into it
  if (lower.includes("<head>")) {
    return content.replace(/<head>/i, `<head>${INJECTED_HEAD}`);
  }

  // If it has <html> but no <head>, add one
  if (lower.includes("<html>")) {
    return content.replace(/<html[^>]*>/i, `$&<head>${INJECTED_HEAD}</head>`);
  }

  // Otherwise wrap the content in a full document
  return `<!DOCTYPE html>
<html>
<head>${INJECTED_HEAD}</head>
<body>${content}</body>
</html>`;
}
