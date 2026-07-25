"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { getPublicEnv } from "@/lib/runtime-env";
import { supabase } from "@/lib/supabase/client";

type Brand = {
  id: string;
  name: string;
  logo_url: string | null;
  created_at: string;
};

export default function BrandDetailPage() {
  const { brandId } = useParams<{ brandId: string }>();
  const router = useRouter();
  const apiBase = getPublicEnv("NEXT_PUBLIC_API_URL");
  const [brand, setBrand] = useState<Brand | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isNotFound, setIsNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    async function loadBrand() {
      setError(null);
      setIsNotFound(false);
      setIsLoading(true);

      try {
        const { data } = await supabase.auth.getSession();
        const session = data.session;
        if (!session) {
          router.push("/login");
          return;
        }

        const response = await fetch(
          `${apiBase}/v1/brands/${encodeURIComponent(brandId)}`,
          {
            headers: { Authorization: `Bearer ${session.access_token}` },
          }
        );
        if (response.status === 404) {
          if (active) {
            setIsNotFound(true);
          }
          return;
        }
        if (!response.ok) {
          throw new Error("Unable to load brand.");
        }

        const body = (await response.json()) as Brand;
        if (active) {
          setBrand(body);
        }
      } catch {
        if (active) {
          setError("Unable to load this brand.");
        }
      } finally {
        if (active) {
          setIsLoading(false);
        }
      }
    }

    void loadBrand();
    return () => {
      active = false;
    };
  }, [apiBase, brandId, router]);

  if (isLoading) {
    return (
      <p className="mx-auto max-w-3xl text-sm text-gray-600">
        Loading brand...
      </p>
    );
  }

  if (isNotFound) {
    return (
      <section className="mx-auto max-w-xl rounded-2xl border p-10 text-center">
        <h1 className="text-2xl font-semibold">Brand not found</h1>
        <p className="mt-2 text-sm text-gray-600">
          This brand does not exist or is not available to you.
        </p>
        <Link
          className="mt-5 inline-block rounded-md border px-4 py-2 text-sm"
          href="/brands"
        >
          Back to brands
        </Link>
      </section>
    );
  }

  if (error || !brand) {
    return (
      <p className="mx-auto max-w-3xl text-sm text-red-600">
        {error ?? "Unable to load this brand."}
      </p>
    );
  }

  return (
    <section className="mx-auto max-w-3xl space-y-8">
      <Link className="text-sm text-gray-600 hover:text-black" href="/brands">
        Back to brands
      </Link>
      <div className="rounded-2xl border p-8">
        <p className="text-sm font-medium uppercase tracking-wider text-gray-500">
          Brand
        </p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight">
          {brand.name}
        </h1>
        <dl className="mt-8 border-t pt-6">
          <dt className="text-sm text-gray-500">Created</dt>
          <dd className="mt-1 font-medium">
            {new Intl.DateTimeFormat(undefined, { dateStyle: "long" }).format(
              new Date(brand.created_at)
            )}
          </dd>
        </dl>
      </div>
    </section>
  );
}
