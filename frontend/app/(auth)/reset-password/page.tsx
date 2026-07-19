"use client";

import { useEffect, useState, type FormEvent } from "react";
import Link from "next/link";

import { supabase } from "@/lib/supabase/client";

export default function ResetPasswordPage() {
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [sessionReady, setSessionReady] = useState(false);

  useEffect(() => {
    let active = true;

    async function establishRecoverySession() {
      // Password reset links use the PKCE flow (?code=...), which requires an
      // explicit exchange — it is not auto-detected from an existing session.
      const code = new URLSearchParams(window.location.search).get("code");

      if (code) {
        const { error: exchangeError } = await supabase.auth.exchangeCodeForSession(code);
        if (!active) return;

        if (exchangeError) {
          setMessage(exchangeError.message);
          return;
        }
      }

      const { data } = await supabase.auth.getSession();
      if (!active) return;

      setSessionReady(Boolean(data.session));
      if (!data.session) {
        setMessage("Open this page from your password reset email link, then choose a new password.");
      }
    }

    void establishRecoverySession();

    return () => {
      active = false;
    };
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setMessage(null);

    const { error } = await supabase.auth.updateUser({ password });

    setSubmitting(false);

    if (error) {
      setMessage(error.message);
      return;
    }

    setMessage("Password updated. You can sign in with the new password now.");
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-md items-center px-6 py-16">
      <form className="w-full space-y-5 rounded-xl border p-6" onSubmit={handleSubmit} noValidate>
        <div>
          <h1 className="text-2xl font-semibold">Choose a new password</h1>
          <p className="mt-1 text-sm text-gray-600">Use at least 8 characters.</p>
        </div>

        <label className="block space-y-2">
          <span className="text-sm font-medium">New password</span>
          <input
            className="w-full rounded-md border px-3 py-2"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            disabled={!sessionReady}
          />
        </label>

        {message ? <p className="text-sm text-gray-700">{message}</p> : null}

        <button
          className="w-full rounded-md bg-black px-4 py-2 text-white disabled:opacity-60"
          type="submit"
          disabled={!sessionReady || submitting}
        >
          {submitting ? "Updating..." : "Update password"}
        </button>

        <p className="text-sm text-gray-500">
          <Link className="underline underline-offset-4" href="/login">
            Back to login
          </Link>
        </p>
      </form>
    </main>
  );
}
