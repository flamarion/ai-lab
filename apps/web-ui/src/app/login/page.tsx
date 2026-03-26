"use client";

import { useAuth } from "@/lib/auth-context";
import { useRouter } from "next/navigation";
import { useEffect, useState, useRef } from "react";

export default function LoginPage() {
  const { user, login, register } = useAuth();
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [pin, setPin] = useState(["", "", "", ""]);
  const [mode, setMode] = useState<"login" | "register">("login");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const pinRefs = useRef<(HTMLInputElement | null)[]>([]);

  useEffect(() => {
    if (user) router.replace("/chat");
  }, [user, router]);

  const pinValue = pin.join("");

  const handlePinChange = (index: number, value: string) => {
    if (!/^\d*$/.test(value)) return;
    const next = [...pin];
    // Handle paste of full PIN
    if (value.length > 1) {
      const digits = value.replace(/\D/g, "").slice(0, 8).split("");
      const newPin = digits.map((d) => d);
      // Pad to at least 4 boxes
      while (newPin.length < 4) newPin.push("");
      setPin(newPin);
      // Focus last filled digit
      const lastIdx = Math.min(digits.length, newPin.length) - 1;
      setTimeout(() => pinRefs.current[lastIdx]?.focus(), 10);
      return;
    }
    next[index] = value;
    setPin(next);
    if (value && index < pin.length - 1) {
      pinRefs.current[index + 1]?.focus();
    }
  };

  const handlePinKeyDown = (index: number, e: React.KeyboardEvent) => {
    if (e.key === "Backspace" && !pin[index] && index > 0) {
      pinRefs.current[index - 1]?.focus();
    }
    if (/^\d$/.test(e.key) && index === pin.length - 1 && pin[index] && pin.length < 8) {
      setPin([...pin, ""]);
      setTimeout(() => pinRefs.current[pin.length]?.focus(), 10);
    }
  };

  const handleSubmit = async () => {
    if (!username.trim()) {
      setError("Username is required");
      return;
    }
    if (pinValue.length < 4) {
      setError("PIN must be at least 4 digits");
      return;
    }
    setError("");
    setLoading(true);
    try {
      if (mode === "login") {
        await login(username.trim(), pinValue);
      } else {
        await register(username.trim(), pinValue);
      }
      router.replace("/chat");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Authentication failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex items-center justify-center min-h-screen p-4">
      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="text-center mb-10">
          <div className="text-5xl mb-3">🧪</div>
          <h1
            className="text-3xl tracking-tight"
            style={{ fontFamily: "var(--font-display)" }}
          >
            AI Lab
          </h1>
          <p className="text-[var(--color-text-muted)] text-sm mt-1">
            Personal AI assistant
          </p>
        </div>

        {/* Mode toggle */}
        <div className="flex rounded-xl bg-[var(--color-bg-secondary)] p-1 mb-6">
          <button
            onClick={() => setMode("login")}
            className={`flex-1 py-2 text-sm rounded-lg transition-colors ${
              mode === "login"
                ? "bg-[var(--color-bg-hover)] text-[var(--color-text)]"
                : "text-[var(--color-text-muted)]"
            }`}
          >
            Sign in
          </button>
          <button
            onClick={() => setMode("register")}
            className={`flex-1 py-2 text-sm rounded-lg transition-colors ${
              mode === "register"
                ? "bg-[var(--color-bg-hover)] text-[var(--color-text)]"
                : "text-[var(--color-text-muted)]"
            }`}
          >
            Create account
          </button>
        </div>

        {/* Username */}
        <div className="mb-6">
          <label className="block text-sm text-[var(--color-text-secondary)] mb-2">
            {mode === "login" ? "Username" : "Choose a username"}
          </label>
          <input
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && username.trim()) {
                pinRefs.current[0]?.focus();
              }
            }}
            className="w-full px-4 py-3 rounded-xl bg-[var(--color-bg-secondary)] border border-[var(--color-border)] text-[var(--color-text)] focus:outline-none focus:border-[var(--color-accent)] transition-colors"
            placeholder="Your name"
            autoFocus
          />
        </div>

        {/* PIN input */}
        <div className="mb-6">
          <label className="block text-sm text-[var(--color-text-secondary)] mb-3">
            {mode === "login" ? "PIN" : "Choose a PIN (4-8 digits)"}
          </label>
          <div className="flex justify-center gap-2">
            {pin.map((digit, i) => (
              <input
                key={i}
                ref={(el) => { pinRefs.current[i] = el; }}
                type="password"
                inputMode="numeric"
                maxLength={1}
                value={digit}
                onChange={(e) => handlePinChange(i, e.target.value)}
                onKeyDown={(e) => handlePinKeyDown(i, e)}
                onKeyUp={(e) => {
                  if (e.key === "Enter") handleSubmit();
                }}
                className="pin-digit"
              />
            ))}
          </div>
        </div>

        {/* Error */}
        {error && (
          <p className="text-[var(--color-error)] text-sm text-center mb-4 animate-fade-in">
            {error}
          </p>
        )}

        {/* Submit */}
        <button
          onClick={handleSubmit}
          disabled={loading || !username.trim() || pinValue.length < 4}
          className="w-full py-3 rounded-xl font-medium transition-all disabled:opacity-40
            bg-[var(--color-accent)] text-[var(--color-bg)] hover:bg-[var(--color-accent-hover)]"
        >
          {loading ? "..." : mode === "login" ? "Sign in" : "Create account"}
        </button>
      </div>
    </div>
  );
}
