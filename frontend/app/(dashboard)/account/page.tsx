"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { z } from "zod";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";

import { supabase } from "@/lib/supabase/client";

const profileFormSchema = z
  .object({
    full_name: z.string(),
    avatar_url: z.string(),
  })
  .superRefine((values, ctx) => {
    const fullName = values.full_name.trim();
    if (values.full_name !== "" && (fullName.length < 2 || fullName.length > 120)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["full_name"],
        message: "Full name must be between 2 and 120 characters.",
      });
    }

    const avatarUrl = values.avatar_url.trim();
    if (values.avatar_url !== "" && !/^https?:\/\/.+/.test(avatarUrl)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["avatar_url"],
        message: "Avatar URL must be a valid http or https URL.",
      });
    }
  });

type ProfileFormValues = z.infer<typeof profileFormSchema>;

type ProfileResponse = {
  user_id: string;
  email: string;
  full_name: string | null;
  avatar_url: string | null;
  created_at: string;
  updated_at: string;
};

export default function AccountPage() {
  const router = useRouter();
  const [email, setEmail] = useState<string>("");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const apiBase = process.env.NEXT_PUBLIC_API_URL ?? "/api";

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<ProfileFormValues>({
    resolver: zodResolver(profileFormSchema),
    defaultValues: { full_name: "", avatar_url: "" },
  });

  useEffect(() => {
    let active = true;

    async function loadProfile() {
      const { data } = await supabase.auth.getSession();
      const session = data.session;

      if (!session) {
        router.push("/login");
        return;
      }

      setEmail(session.user.email ?? "");

      const response = await fetch(`${apiBase}/v1/me`, {
        headers: { Authorization: `Bearer ${session.access_token}` },
      });

      if (!response.ok) {
        setLoadError("Unable to load your profile.");
        return;
      }

      const profile: ProfileResponse = await response.json();
      if (!active) {
        return;
      }

      reset({
        full_name: profile.full_name ?? "",
        avatar_url: profile.avatar_url ?? "",
      });
    }

    void loadProfile();

    return () => {
      active = false;
    };
  }, [apiBase, reset, router]);

  const submit = useMemo(
    () =>
      handleSubmit(async (values) => {
        setStatus(null);
        setLoadError(null);

        const { data } = await supabase.auth.getSession();
        const session = data.session;
        if (!session) {
          router.push("/login");
          return;
        }

        const payload: Record<string, string> = {};
        const fullName = values.full_name.trim();
        const avatarUrl = values.avatar_url.trim();

        if (fullName) {
          payload.full_name = fullName;
        }
        if (avatarUrl) {
          payload.avatar_url = avatarUrl;
        }

        const response = await fetch(`${apiBase}/v1/me`, {
          method: "PATCH",
          headers: {
            Authorization: `Bearer ${session.access_token}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify(payload),
        });

        const body = await response.json();
        if (!response.ok) {
          setLoadError(body?.error?.message ?? "Unable to save profile.");
          return;
        }

        reset({
          full_name: body.full_name ?? "",
          avatar_url: body.avatar_url ?? "",
        });
        setStatus("Profile updated.");
      }),
    [apiBase, handleSubmit, reset, router],
  );

  return (
    <section className="mx-auto max-w-2xl space-y-8">
      <div>
        <h1 className="text-2xl font-semibold">Account settings</h1>
        <p className="mt-1 text-sm text-gray-600">View and edit your own profile.</p>
      </div>

      <div className="rounded-xl border p-5">
        <p className="text-sm text-gray-500">Email</p>
        <p className="mt-1 font-medium">{email || "Loading..."}</p>
      </div>

      <form className="space-y-5 rounded-xl border p-6" onSubmit={submit} noValidate>
        <label className="block space-y-2">
          <span className="text-sm font-medium">Full name</span>
          <input className="w-full rounded-md border px-3 py-2" type="text" {...register("full_name")} />
          {errors.full_name ? <p className="text-sm text-red-600">{errors.full_name.message}</p> : null}
        </label>

        <label className="block space-y-2">
          <span className="text-sm font-medium">Avatar URL</span>
          <input className="w-full rounded-md border px-3 py-2" type="url" {...register("avatar_url")} />
          {errors.avatar_url ? <p className="text-sm text-red-600">{errors.avatar_url.message}</p> : null}
        </label>

        {loadError ? <p className="text-sm text-red-600">{loadError}</p> : null}
        {status ? <p className="text-sm text-green-700">{status}</p> : null}

        <button className="rounded-md bg-black px-4 py-2 text-white disabled:opacity-60" type="submit" disabled={isSubmitting}>
          {isSubmitting ? "Saving..." : "Save changes"}
        </button>
      </form>
    </section>
  );
}
