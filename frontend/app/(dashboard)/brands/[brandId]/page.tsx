"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type FormEvent,
} from "react";

import { getPublicEnv } from "@/lib/runtime-env";
import { supabase } from "@/lib/supabase/client";

type Brand = {
  id: string;
  name: string;
  logo_url: string | null;
  created_at: string;
};

const MAX_LOGO_BYTES = 5 * 1024 * 1024;
const LOGO_TYPES = new Set(["image/png", "image/jpeg", "image/webp"]);

export default function BrandDetailPage() {
  const { brandId } = useParams<{ brandId: string }>();
  const router = useRouter();
  const apiBase = getPublicEnv("NEXT_PUBLIC_API_URL");
  const [brand, setBrand] = useState<Brand | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isNotFound, setIsNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [logoError, setLogoError] = useState<string | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [isRemoving, setIsRemoving] = useState(false);
  const [logoRevision, setLogoRevision] = useState(0);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let active = true;

    async function loadBrand() {
      setError(null);
      setIsNotFound(false);
      setIsLoading(true);
      setBrand(null);

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

  function selectLogo(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
    setLogoError(null);

    if (!file) {
      setSelectedFile(null);
      return;
    }
    if (!LOGO_TYPES.has(file.type)) {
      setLogoError("Choose a PNG, JPEG, or WebP image.");
      setSelectedFile(null);
      event.target.value = "";
      return;
    }
    if (file.size > MAX_LOGO_BYTES) {
      setLogoError("Logo must be 5 MB or smaller.");
      setSelectedFile(null);
      event.target.value = "";
      return;
    }

    setSelectedFile(file);
  }

  async function uploadLogo(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedFile) {
      setLogoError("Choose an image to upload.");
      return;
    }

    setLogoError(null);
    setIsUploading(true);
    try {
      const { data } = await supabase.auth.getSession();
      const session = data.session;
      if (!session) {
        router.push("/login");
        return;
      }

      const formData = new FormData();
      formData.append("file", selectedFile);
      const response = await fetch(
        `${apiBase}/v1/brands/${encodeURIComponent(brandId)}/logo`,
        {
          method: "POST",
          headers: { Authorization: `Bearer ${session.access_token}` },
          body: formData,
        }
      );
      const body = await response.json().catch(() => null);
      if (!response.ok) {
        setLogoError(body?.error?.message ?? "Unable to upload the logo.");
        return;
      }

      setBrand(body as Brand);
      setLogoRevision((revision) => revision + 1);
      setSelectedFile(null);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
      window.dispatchEvent(new Event("postforge:brands-changed"));
    } catch {
      setLogoError("Unable to upload the logo.");
    } finally {
      setIsUploading(false);
    }
  }

  async function removeLogo() {
    setLogoError(null);
    setIsRemoving(true);
    try {
      const { data } = await supabase.auth.getSession();
      const session = data.session;
      if (!session) {
        router.push("/login");
        return;
      }

      const response = await fetch(
        `${apiBase}/v1/brands/${encodeURIComponent(brandId)}/logo`,
        {
          method: "DELETE",
          headers: { Authorization: `Bearer ${session.access_token}` },
        }
      );
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        setLogoError(body?.error?.message ?? "Unable to remove the logo.");
        return;
      }

      setBrand((current) =>
        current ? { ...current, logo_url: null } : current
      );
      setSelectedFile(null);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
      window.dispatchEvent(new Event("postforge:brands-changed"));
    } catch {
      setLogoError("Unable to remove the logo.");
    } finally {
      setIsRemoving(false);
    }
  }

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

      <div className="rounded-2xl border p-8">
        <h2 className="text-lg font-semibold">Brand logo</h2>
        <p className="mt-1 text-sm text-gray-600">
          PNG, JPEG, or WebP, up to 5 MB.
        </p>

        <div className="mt-6 flex flex-col gap-6 sm:flex-row sm:items-start">
          <div className="flex h-32 w-32 shrink-0 items-center justify-center overflow-hidden rounded-xl border bg-gray-50">
            {brand.logo_url ? (
              // Runtime-configured Supabase hosts cannot be declared in next/image remotePatterns.
              // eslint-disable-next-line @next/next/no-img-element
              <img
                className="h-full w-full object-contain"
                src={`${brand.logo_url}?v=${logoRevision}`}
                alt={`${brand.name} logo`}
              />
            ) : (
              <span className="text-sm text-gray-500">No logo</span>
            )}
          </div>

          <form className="flex-1 space-y-4" onSubmit={uploadLogo}>
            <input
              ref={fileInputRef}
              className="block w-full text-sm file:mr-4 file:rounded-md file:border file:bg-white file:px-3 file:py-2 file:text-sm"
              type="file"
              accept="image/png,image/jpeg,image/webp"
              disabled={isUploading || isRemoving}
              onChange={selectLogo}
            />
            {logoError ? (
              <p className="text-sm text-red-600" role="alert">
                {logoError}
              </p>
            ) : null}
            <div className="flex flex-wrap gap-3">
              <button
                className="rounded-md bg-black px-4 py-2 text-sm text-white disabled:cursor-not-allowed disabled:opacity-60"
                type="submit"
                disabled={!selectedFile || isUploading || isRemoving}
              >
                {isUploading
                  ? "Uploading..."
                  : brand.logo_url
                    ? "Replace logo"
                    : "Upload logo"}
              </button>
              {brand.logo_url ? (
                <button
                  className="rounded-md border px-4 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-60"
                  type="button"
                  disabled={isUploading || isRemoving}
                  onClick={removeLogo}
                >
                  {isRemoving ? "Removing..." : "Remove logo"}
                </button>
              ) : null}
            </div>
          </form>
        </div>
      </div>
    </section>
  );
}
