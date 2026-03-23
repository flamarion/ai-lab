"use client";

import { useAuth } from "@/lib/auth-context";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

export default function Home() {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading) {
      router.replace(user ? "/chat" : "/login");
    }
  }, [user, loading, router]);

  return (
    <div className="flex items-center justify-center min-h-screen">
      <div className="typing-dot w-2 h-2 rounded-full bg-[var(--color-accent)] mx-1" />
      <div className="typing-dot w-2 h-2 rounded-full bg-[var(--color-accent)] mx-1" />
      <div className="typing-dot w-2 h-2 rounded-full bg-[var(--color-accent)] mx-1" />
    </div>
  );
}
