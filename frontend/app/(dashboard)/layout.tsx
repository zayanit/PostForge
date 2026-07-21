"use client";

import { useRouter } from "next/navigation";
import type { ReactNode } from "react";

import { supabase } from "@/lib/supabase/client";

export default function DashboardLayout({ children }: { children: ReactNode }) {
  const router = useRouter();

  async function handleLogout() {
    await supabase.auth.signOut();
    router.push("/login");
  }

  return (
    <div className="min-h-screen">
      <header className="flex items-center justify-between border-b px-6 py-4">
        <span className="font-semibold">PostForge</span>
        <button className="rounded-md border px-3 py-2 text-sm" onClick={handleLogout} type="button">
          Log out
        </button>
      </header>
      <main className="px-6 py-8">{children}</main>
    </div>
  );
}
