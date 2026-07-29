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
  cleanup_state: "normal" | "cleanup_required";
  kit_status?: "not_started" | "in_progress" | "complete";
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
  const [confirmationName, setConfirmationName] = useState("");
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
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

  async function deleteBrand(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (confirmationName !== brand?.name) {
      setDeleteError("Type the brand name exactly to confirm deletion.");
      return;
    }

    setDeleteError(null);
    setIsDeleting(true);
    try {
      const { data } = await supabase.auth.getSession();
      const session = data.session;
      if (!session) {
        router.push("/login");
        return;
      }

      const brandPath = `${apiBase}/v1/brands/${encodeURIComponent(brandId)}`;
      let response: Response | null = null;
      try {
        response = await fetch(brandPath, {
          method: "DELETE",
          headers: {
            Authorization: `Bearer ${session.access_token}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ confirm_name: confirmationName }),
        });
      } catch {
        // Reconcile below before deciding whether an ambiguous deletion completed.
      }

      if (response?.status !== 204) {
        if (response === null || response.status === 404 || response.status >= 500) {
          try {
            const listResponse = await fetch(`${apiBase}/v1/brands`, {
              headers: { Authorization: `Bearer ${session.access_token}` },
            });
            if (!listResponse.ok) throw new Error("Unable to reconcile brands.");

            const body = (await listResponse.json()) as { brands: Brand[] };
            const retainedBrand = body.brands.find((item) => item.id === brandId);
            if (!retainedBrand) {
              window.dispatchEvent(new Event("postforge:brands-changed"));
              router.push("/brands");
              router.refresh();
              return;
            }

            setBrand(retainedBrand);
            setDeleteError("Brand cleanup did not complete. Retry deletion.");
          } catch {
            setDeleteError("The deletion outcome is unknown. Refresh or retry deletion.");
          }
          return;
        }

        const body = await response.json().catch(() => null);
        setDeleteError(body?.error?.message ?? "Unable to delete the brand.");
        return;
      }

      window.dispatchEvent(new Event("postforge:brands-changed"));
      router.push("/brands");
      router.refresh();
    } catch {
      setDeleteError("Unable to delete the brand.");
    } finally {
      setIsDeleting(false);
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

  const cleanupRequired = brand.cleanup_state === "cleanup_required";
  const kitStatus = brand.kit_status ?? "not_started";
  const kitStatusLabel = {
    not_started: "Not started",
    in_progress: "In progress",
    complete: "Complete",
  }[kitStatus];

  return (
    <section className="mx-auto max-w-3xl space-y-8">
      <Link className="text-sm text-gray-600 hover:text-black" href="/brands">
        Back to brands
      </Link>
      <div className="rounded-2xl border p-8">
        <p className="text-sm font-medium uppercase tracking-wider text-gray-500">
          Brand
        </p>
        <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
          <h1 className="text-3xl font-semibold tracking-tight">{brand.name}</h1>
          {cleanupRequired ? (
            <span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-medium text-amber-900">
              Cleanup required
            </span>
          ) : null}
        </div>
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
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold">Brand Kit</h2>
            <p className="mt-1 text-sm text-gray-600">
              Define the voice, audience, and visual direction for this brand.
            </p>
          </div>
          <span className="rounded-full bg-gray-100 px-3 py-1 text-xs font-medium text-gray-700">
            {kitStatusLabel}
          </span>
        </div>
        {cleanupRequired || isDeleting ? (
          <p className="mt-5 text-sm font-medium text-amber-800">
            Brand Kit is unavailable while brand cleanup is in progress.
          </p>
        ) : (
          <Link
            className="mt-5 inline-block rounded-md border px-4 py-2 text-sm font-medium hover:border-gray-400"
            href={`/brands/${brand.id}/kit`}
          >
            {kitStatus === "complete" ? "Review Brand Kit" : "Set up Brand Kit"}
          </Link>
        )}
      </div>

      <div className="rounded-2xl border p-8">
        <h2 className="text-lg font-semibold">Provider keys</h2>
        <p className="mt-1 text-sm text-gray-600">
          Configure brand-scoped OpenAI and Gemini credentials without exposing them after submission.
        </p>
        {cleanupRequired || isDeleting ? (
          <p className="mt-5 text-sm font-medium text-amber-800">
            Provider setup is unavailable while brand deletion is in progress.
          </p>
        ) : (
          <Link
            className="mt-5 inline-block rounded-md border px-4 py-2 text-sm font-medium hover:border-gray-400"
            href={`/brands/${brand.id}/keys`}
          >
            Manage provider keys
          </Link>
        )}
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
              disabled={cleanupRequired || isUploading || isRemoving || isDeleting}
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
                disabled={cleanupRequired || !selectedFile || isUploading || isRemoving || isDeleting}
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
                  disabled={cleanupRequired || isUploading || isRemoving || isDeleting}
                  onClick={removeLogo}
                >
                  {isRemoving ? "Removing..." : "Remove logo"}
                </button>
              ) : null}
            </div>
          </form>
        </div>
      </div>

      <div className="rounded-2xl border border-red-200 bg-red-50/40 p-8">
        <h2 className="text-lg font-semibold text-red-900">Delete brand</h2>
        <p className="mt-1 text-sm text-red-800">
          This permanently deletes the brand, provider keys, and all stored assets.
          This action cannot be undone.
        </p>

        <form className="mt-6 space-y-4" onSubmit={deleteBrand}>
          <label className="block text-sm font-medium text-red-950">
            Type <span className="font-semibold">{brand.name}</span> to confirm
            <input
              className="mt-2 block w-full rounded-md border border-red-300 bg-white px-3 py-2 text-sm text-gray-950 outline-none focus:border-red-600"
              type="text"
              value={confirmationName}
              disabled={isDeleting || isUploading || isRemoving}
              autoComplete="off"
              onChange={(event) => {
                setConfirmationName(event.target.value);
                setDeleteError(null);
              }}
            />
          </label>
          {deleteError ? (
            <p className="text-sm text-red-700" role="alert">
              {deleteError}
            </p>
          ) : null}
          <button
            className="rounded-md bg-red-700 px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
            type="submit"
            disabled={
              confirmationName !== brand.name ||
              isDeleting ||
              isUploading ||
              isRemoving
            }
          >
            {isDeleting
              ? "Deleting..."
              : cleanupRequired
                ? "Retry brand deletion"
                : "Delete brand permanently"}
          </button>
        </form>
      </div>
    </section>
  );
}
