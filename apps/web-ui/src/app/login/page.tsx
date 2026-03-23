"use client";

import { useAuth } from "@/lib/auth-context";
import { auth as authApi } from "@/lib/api";
import { useRouter } from "next/navigation";
import { useEffect, useState, useRef } from "react";

export default function LoginPage() {
  const { user, login, register } = useAuth();
  const router = useRouter();
  const [users, setUsers] = useState<string[]>([]);
  const [selectedUser, setSelectedUser] = useState("");
  const [pin, setPin] = useState(["", "", "", ""]);
  const [mode, setMode] = useState<"login" | "register">("login");
  const [newUsername, setNewUsername] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const pinRefs = useRef<(HTMLInputElement | null)[]>([]);

  useEffect(() => {
    if (user) router.replace("/chat");
  }, [user, router]);

  useEffect(() => {
    authApi.listUsers().then((data) => {
      const names = data.users.map((u) => u.username);
      setUsers(names);
      if (names.length > 0) setSelectedUser(names[0]);
      if (names.length === 0) setMode("register");
    }).catch(() => {});
  }, []);

  const pinValue = pin.join("");

  const handlePinChange = (index: number, value: string) => {
    if (!/^\d*$/.test(value)) return;
    const next = [...pin];
    // Handle paste of full PIN
    if (value.length > 1) {
      const digits = value.slice(0, 8).split("");
      digits.forEach((d, i) => { if (i < 8) next[i] = d; });
      // Extend array if needed
      while (next.length < digits.length) next.push("");
      setPin(next.slice(0, Math.max(4, digits.length)));
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
    // Add more digits beyond 4
    if (/^\d$/.test(e.key) && index === pin.length - 1 && pin[index] && pin.length < 8) {
      setPin([...pin, ""]);
      setTimeout(() => pinRefs.current[pin.length]?.focus(), 10);
    }
  };

  const handleSubmit = async () => {
    if (pinValue.length < 4) {
      setError("PIN must be at least 4 digits");
      return;
    }
    setError("");
    setLoading(true);
    try {
      if (mode === "login") {
        await login(selectedUser, pinValue);
      } else {
        if (!newUsername.trim()) {
          setError("Username is required");
          setLoading(false);
          return;
        }
        await register(newUsername.trim(), pinValue);
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
        {users.length > 0 && (
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
        )}

        {/* Login: user selector */}
        {mode === "login" && users.length > 0 && (
          <div className="mb-6">
            <label className="block text-sm text-[var(--color-text-secondary)] mb-2">
              Who are you?
            </label>
            <div className="grid grid-cols-2 gap-2">
              {users.map((u) => (
                <button
                  key={u}
                  onClick={() => setSelectedUser(u)}
                  className={`px-4 py-3 rounded-xl text-sm transition-all ${
                    selectedUser === u
                      ? "bg-[var(--color-accent-soft)] border-[var(--color-accent)] border text-[var(--color-accent)]"
                      : "bg-[var(--color-bg-secondary)] border border-[var(--color-border)] text-[var(--color-text-secondary)] hover:border-[var(--color-border-light)]"
                  }`}
                >
                  {u}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Register: username */}
        {mode === "register" && (
          <div className="mb-6">
            <label className="block text-sm text-[var(--color-text-secondary)] mb-2">
              Choose a username
            </label>
            <input
              type="text"
              value={newUsername}
              onChange={(e) => setNewUsername(e.target.value)}
              className="w-full px-4 py-3 rounded-xl bg-[var(--color-bg-secondary)] border border-[var(--color-border)] text-[var(--color-text)] focus:outline-none focus:border-[var(--color-accent)] transition-colors"
              placeholder="Your name"
              autoFocus
            />
          </div>
        )}

        {/* PIN input */}
        <div className="mb-6">
          <label className="block text-sm text-[var(--color-text-secondary)] mb-3">
            {mode === "login" ? "Enter your PIN" : "Choose a PIN (4-8 digits)"}
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
          disabled={loading || pinValue.length < 4}
          className="w-full py-3 rounded-xl font-medium transition-all disabled:opacity-40
            bg-[var(--color-accent)] text-[var(--color-bg)] hover:bg-[var(--color-accent-hover)]"
        >
          {loading ? "..." : mode === "login" ? "Sign in" : "Create account"}
        </button>
      </div>
    </div>
  );
}
