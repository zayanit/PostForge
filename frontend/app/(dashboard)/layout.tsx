"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { getPublicEnv } from "@/lib/runtime-env";
import { supabase } from "@/lib/supabase/client";

type Brand = {
  id: string;
  name: string;
};

export default function DashboardLayout({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const apiBase = getPublicEnv("NEXT_PUBLIC_API_URL");
  const [brands, setBrands] = useState<Brand[]>([]);
  const [isLoadingBrands, setIsLoadingBrands] = useState(true);
  const [brandsError, setBrandsError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    async function loadBrands() {
      setIsLoadingBrands(true);
      try {
        const { data } = await supabase.auth.getSession();
        const session = data.session;
        if (!session) {
          return;
        }

        const response = await fetch(`${apiBase}/v1/brands`, {
          headers: { Authorization: `Bearer ${session.access_token}` },
        });
        if (!response.ok) {
          if (active) {
            setBrandsError("Unable to load your brands.");
          }
          return;
        }

        const body = (await response.json()) as { brands: Brand[] };
        if (active) {
          setBrands(body.brands);
          setBrandsError(null);
        }
      } catch {
        if (active) {
          setBrandsError("Unable to load your brands.");
        }
      } finally {
        if (active) {
          setIsLoadingBrands(false);
        }
      }
    }

    function refreshBrands() {
      void loadBrands();
    }

    refreshBrands();
    window.addEventListener("postforge:brands-changed", refreshBrands);
    return () => {
      active = false;
      window.removeEventListener("postforge:brands-changed", refreshBrands);
    };
  }, [apiBase]);

  const pathBrandId = pathname.match(/^\/brands\/([^/]+)(?:\/.*)?$/)?.[1];
  const selectedBrandId = pathBrandId === "new" ? "" : (pathBrandId ?? "");

  async function handleLogout() {
    await supabase.auth.signOut();
    router.push("/login");
  }

  return (
    <div className="min-h-screen">
      <header className="border-b px-4 py-3 sm:px-6">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-4">
          <Link className="font-semibold" href="/">
            PostForge
          </Link>
          <nav className="flex items-center gap-4 text-sm">
            <Link className="text-gray-600 hover:text-black" href="/brands">
              Brands
            </Link>
            <Link className="text-gray-600 hover:text-black" href="/account">
              Account
            </Link>
          </nav>
          <label className="ml-auto flex items-center gap-2 text-sm">
            <span className="sr-only">Current brand</span>
            {brandsError ? (
              <span className="text-xs text-red-600">{brandsError}</span>
            ) : null}
            <select
              className="max-w-48 rounded-md border bg-white px-3 py-2"
              value={selectedBrandId}
              disabled={isLoadingBrands || brands.length === 0}
              onChange={(event) => {
                if (event.target.value) {
                  router.push(`/brands/${event.target.value}`);
                }
              }}
            >
              <option value="">
                {isLoadingBrands
                  ? "Loading brands..."
                  : brandsError
                    ? "Brands unavailable"
                    : "Choose brand"}
              </option>
              {brands.map((brand) => (
                <option value={brand.id} key={brand.id}>
                  {brand.name}
                </option>
              ))}
            </select>
          </label>
          <button
            className="rounded-md border px-3 py-2 text-sm"
            onClick={handleLogout}
            type="button"
          >
            Log out
          </button>
        </div>
      </header>
      <main className="px-6 py-8">{children}</main>
    </div>
  );
}
