"use client";

import { useState, type FormEvent } from "react";

import { supabase } from "@/lib/supabase/client";

type FormState = {
  email: string;
  password: string;
};

type FieldErrors = Partial<Record<keyof FormState, string>>;

function validate(values: FormState): FieldErrors {
  const errors: FieldErrors = {};

  if (!values.email.trim()) {
    errors.email = "Email is required.";
  } else if (!/^\S+@\S+\.\S+$/.test(values.email.trim())) {
    errors.email = "Enter a valid email address.";
  }

  if (values.password.length < 8) {
    errors.password = "Password must be at least 8 characters.";
  }

  return errors;
}

export default function SignupPage() {
  const [values, setValues] = useState<FormState>({ email: "", password: "" });
  const [errors, setErrors] = useState<FieldErrors>({});
  const [status, setStatus] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const nextErrors = validate(values);
    setErrors(nextErrors);
    setStatus(null);

    if (Object.keys(nextErrors).length > 0) {
      return;
    }

    setSubmitting(true);
    const { data, error } = await supabase.auth.signUp({
      email: values.email.trim(),
      password: values.password,
    });
    setSubmitting(false);

    if (error) {
      setStatus(error.message);
      return;
    }

    // Email confirmation is disabled (FR-005), so signUp() already establishes
    // a live session — don't tell an already-authenticated user to "sign in".
    setStatus(
      data.session
        ? "Account created. You're signed in."
        : "Account created. You can now sign in."
    );
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-md items-center px-6 py-16">
      <form className="w-full space-y-5 rounded-xl border p-6" onSubmit={handleSubmit} noValidate>
        <div>
          <h1 className="text-2xl font-semibold">Create your account</h1>
          <p className="mt-1 text-sm text-gray-600">Use your email and a password with at least 8 characters.</p>
        </div>

        <label className="block space-y-2">
          <span className="text-sm font-medium">Email</span>
          <input
            className="w-full rounded-md border px-3 py-2"
            type="email"
            value={values.email}
            onChange={(event) => setValues((current) => ({ ...current, email: event.target.value }))}
            aria-invalid={Boolean(errors.email)}
          />
          {errors.email ? <p className="text-sm text-red-600">{errors.email}</p> : null}
        </label>

        <label className="block space-y-2">
          <span className="text-sm font-medium">Password</span>
          <input
            className="w-full rounded-md border px-3 py-2"
            type="password"
            value={values.password}
            onChange={(event) => setValues((current) => ({ ...current, password: event.target.value }))}
            aria-invalid={Boolean(errors.password)}
          />
          {errors.password ? <p className="text-sm text-red-600">{errors.password}</p> : null}
        </label>

        {status ? <p className="text-sm text-gray-700">{status}</p> : null}

        <button
          className="w-full rounded-md bg-black px-4 py-2 text-white disabled:opacity-60"
          type="submit"
          disabled={submitting}
        >
          {submitting ? "Creating account..." : "Sign up"}
        </button>
      </form>
    </main>
  );
}
