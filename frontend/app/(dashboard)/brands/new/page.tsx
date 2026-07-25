"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { getPublicEnv } from "@/lib/runtime-env";
import { supabase } from "@/lib/supabase/client";

function normalizeBrandName(value: string) {
  return value.replace(/^ +| +$/g, "");
}

const brandFormSchema = z.object({
  name: z.string().superRefine((value, ctx) => {
    const normalized = normalizeBrandName(value);
    if (normalized.length < 2 || normalized.length > 120) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Brand name must be between 2 and 120 characters.",
      });
    }
  }),
});

type BrandFormValues = z.infer<typeof brandFormSchema>;

type BrandResponse = {
  id: string;
  name: string;
  logo_url: string | null;
  created_at: string;
};

type ErrorResponse = {
  error?: {
    code?: string;
    message?: string;
  };
};

export default function NewBrandPage() {
  const router = useRouter();
  const apiBase = getPublicEnv("NEXT_PUBLIC_API_URL");
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<BrandFormValues>({
    resolver: zodResolver(brandFormSchema),
    defaultValues: { name: "" },
  });

  async function submit(values: BrandFormValues) {
    setFormError(null);

    try {
      const { data } = await supabase.auth.getSession();
      const session = data.session;
      if (!session) {
        router.push("/login");
        return;
      }

      const response = await fetch(`${apiBase}/v1/brands`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${session.access_token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ name: normalizeBrandName(values.name) }),
      });
      const body = (await response.json().catch(() => null)) as
        BrandResponse | ErrorResponse | null;

      if (!response.ok) {
        const error = (body as ErrorResponse | null)?.error;
        if (error?.code === "BRAND_NAME_TAKEN") {
          setError("name", {
            type: "server",
            message:
              error.message ?? "You already have a brand with this name.",
          });
          return;
        }

        setFormError(error?.message ?? "Unable to create your brand.");
        return;
      }

      const brand = body as BrandResponse;
      router.push(`/brands/${brand.id}`);
    } catch {
      setFormError("Unable to create your brand.");
    }
  }

  return (
    <section className="mx-auto max-w-xl space-y-8">
      <div>
        <p className="text-sm font-medium uppercase tracking-wider text-gray-500">
          New brand
        </p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight">
          Create your brand
        </h1>
        <p className="mt-2 text-sm text-gray-600">
          Give this workspace a distinct name. You can add its visual identity
          later.
        </p>
      </div>

      <form
        className="space-y-6 rounded-xl border bg-white p-6 shadow-sm"
        onSubmit={handleSubmit(submit)}
        noValidate
      >
        <label className="block space-y-2">
          <span className="text-sm font-medium">Brand name</span>
          <input
            className="w-full rounded-md border px-3 py-2 outline-none transition focus:border-black focus:ring-2 focus:ring-black/10"
            type="text"
            autoComplete="organization"
            autoFocus
            aria-invalid={errors.name ? "true" : "false"}
            aria-describedby={errors.name ? "brand-name-error" : undefined}
            {...register("name")}
          />
          {errors.name ? (
            <p id="brand-name-error" className="text-sm text-red-600">
              {errors.name.message}
            </p>
          ) : (
            <p className="text-sm text-gray-500">
              Between 2 and 120 characters.
            </p>
          )}
        </label>

        {formError ? <p className="text-sm text-red-600">{formError}</p> : null}

        <div className="flex items-center gap-3">
          <button
            className="rounded-md bg-black px-4 py-2 text-white disabled:cursor-not-allowed disabled:opacity-60"
            type="submit"
            disabled={isSubmitting}
          >
            {isSubmitting ? "Creating..." : "Create brand"}
          </button>
          <button
            className="rounded-md border px-4 py-2 text-sm disabled:opacity-60"
            type="button"
            disabled={isSubmitting}
            onClick={() => router.push("/")}
          >
            Cancel
          </button>
        </div>
      </form>
    </section>
  );
}
