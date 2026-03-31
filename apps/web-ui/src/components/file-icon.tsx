import { FileText, FileSpreadsheet, FileCode, FileJson } from "lucide-react";

/** Pick a file icon based on extension. */
export default function FileIcon({ name, size = 14 }: { name: string; size?: number }) {
  const ext = name.split(".").pop()?.toLowerCase() || "";
  if (ext === "csv") return <FileSpreadsheet size={size} className="text-green-500 shrink-0" />;
  if (ext === "json") return <FileJson size={size} className="text-yellow-500 shrink-0" />;
  if (["py", "js", "ts", "go", "rs", "java", "sh", "sql", "html", "css"].includes(ext))
    return <FileCode size={size} className="text-blue-500 shrink-0" />;
  return <FileText size={size} className="text-[var(--color-text-muted)] shrink-0" />;
}
