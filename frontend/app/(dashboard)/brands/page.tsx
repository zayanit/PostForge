"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { getPublicEnv } from "@/lib/runtime-env";
import { supabase } from "@/lib/supabase/client";

type Brand = {
  id: string;
  name: string;
  logo_url: string | null;
  cleanup_state: "normal" | "cleanup_required";
  kit_status: "not_started" | "in_progress" | "complete";
  created_at: string;
};

const KIT_STATUS_LABELS = {
  not_started: "Not started",
  in_progress: "In progress",
  complete: "Complete",
} as const;

export default function BrandsPage() {
  const router = useRouter();
  const apiBase = getPublicEnv("NEXT_PUBLIC_API_URL");
  const [brands, setBrands] = useState<Brand[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    async function loadBrands() {
      setError(null);
      setIsLoading(true);

      try {
        const { data } = await supabase.auth.getSession();
        const session = data.session;
        if (!session) {
          router.push("/login");
          return;
        }

        const response = await fetch(`${apiBase}/v1/brands`, {
          headers: { Authorization: `Bearer ${session.access_token}` },
        });
        if (!response.ok) {
          throw new Error("Unable to load brands.");
        }

        const body = (await response.json()) as { brands: Brand[] };
        if (active) {
          setBrands(body.brands);
        }
      } catch {
        if (active) {
          setError("Unable to load your brands.");
        }
      } finally {
        if (active) {
          setIsLoading(false);
        }
      }
    }

    void loadBrands();
    return () => {
      active = false;
    };
  }, [apiBase, router]);

  return (
    <section className="mx-auto max-w-5xl space-y-8">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-sm font-medium uppercase tracking-wider text-gray-500">
            Workspace
          </p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight">
            Your brands
          </h1>
          <p className="mt-2 text-sm text-gray-600">
            Choose a brand or create a new identity.
          </p>
        </div>
        <Link
          className="w-fit rounded-md bg-black px-4 py-2 text-sm text-white"
          href="/brands/new"
        >
          Create brand
        </Link>
      </div>

      {isLoading ? (
        <p className="text-sm text-gray-600">Loading brands...</p>
      ) : null}
      {error ? (
        <p className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </p>
      ) : null}

      {!isLoading && !error && brands.length === 0 ? (
        <div className="rounded-2xl border border-dashed p-10 text-center">
          <h2 className="text-lg font-semibold">Create your first brand</h2>
          <p className="mx-auto mt-2 max-w-md text-sm text-gray-600">
            Brands keep each identity and its future content work separate.
          </p>
          <Link
            className="mt-5 inline-block rounded-md border px-4 py-2 text-sm font-medium"
            href="/brands/new"
          >
            Get started
          </Link>
        </div>
      ) : null}

      {!isLoading && !error && brands.length > 0 ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {brands.map((brand) => (
            <Link
              className="group rounded-xl border p-5 transition hover:-translate-y-0.5 hover:border-gray-400 hover:shadow-sm"
              href={`/brands/${brand.id}`}
              key={brand.id}
            >
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-gray-100 text-sm font-semibold">
                {brand.name.slice(0, 2).toUpperCase()}
              </div>
              <div className="mt-5 flex flex-wrap items-center justify-between gap-2">
                <h2 className="font-semibold group-hover:underline">
                  {brand.name}
                </h2>
                {brand.cleanup_state === "cleanup_required" ? (
                  <span className="rounded-full bg-amber-100 px-2.5 py-1 text-xs font-medium text-amber-900">
                    Cleanup required
                  </span>
                ) : null}
                <span className="rounded-full bg-gray-100 px-2.5 py-1 text-xs font-medium text-gray-700">
                  {KIT_STATUS_LABELS[brand.kit_status]}
                </span>
              </div>
              <p className="mt-1 text-xs text-gray-500">
                Created {new Date(brand.created_at).toLocaleDateString()}
              </p>
            </Link>
          ))}
        </div>
      ) : null}
    </section>
  );
}
