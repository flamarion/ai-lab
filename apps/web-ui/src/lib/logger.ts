/**
 * Structured JSON logger for the web UI.
 *
 * - Dev mode (NODE_ENV !== "production"): logs JSON strings to the console.
 * - Production: silent (no-op) to avoid noise in user browsers.
 *
 * Usage:
 *   import { logger } from "@/lib/logger";
 *   logger.info("SSE event received", { event: "status", detail: "thinking" });
 *   logger.error("Stream failed", { error: err.message, conversation_id: id });
 *
 * Output (dev only):
 *   {"ts":"2026-04-08T...","level":"INFO","component":"chat","msg":"SSE event","event":"status"}
 *
 * Ready for telemetry: swap the console calls for a fetch() to your
 * collector endpoint when needed.
 */

type LogLevel = "DEBUG" | "INFO" | "WARN" | "ERROR";

interface LogEntry {
  ts: string;
  level: LogLevel;
  component: string;
  msg: string;
  [key: string]: unknown;
}

const IS_DEV = process.env.NODE_ENV !== "production";

const LEVEL_RANK: Record<LogLevel, number> = {
  DEBUG: 0,
  INFO: 1,
  WARN: 2,
  ERROR: 3,
};

// Minimum level — could be driven by an env var or localStorage later
const MIN_LEVEL: LogLevel = "DEBUG";

function emit(level: LogLevel, component: string, msg: string, extra?: Record<string, unknown>) {
  if (!IS_DEV) return;
  if (LEVEL_RANK[level] < LEVEL_RANK[MIN_LEVEL]) return;

  const entry: LogEntry = {
    ts: new Date().toISOString(),
    level,
    component,
    msg,
    ...extra,
  };

  // Use the appropriate console method for dev tools filtering
  switch (level) {
    case "ERROR":
      console.error(JSON.stringify(entry));
      break;
    case "WARN":
      console.warn(JSON.stringify(entry));
      break;
    default:
      console.log(JSON.stringify(entry));
  }
}

/** Create a scoped logger for a specific component. */
export function createLogger(component: string) {
  return {
    debug: (msg: string, extra?: Record<string, unknown>) => emit("DEBUG", component, msg, extra),
    info: (msg: string, extra?: Record<string, unknown>) => emit("INFO", component, msg, extra),
    warn: (msg: string, extra?: Record<string, unknown>) => emit("WARN", component, msg, extra),
    error: (msg: string, extra?: Record<string, unknown>) => emit("ERROR", component, msg, extra),
  };
}

/** Default logger — use createLogger("component") for scoped logging. */
export const logger = createLogger("app");
