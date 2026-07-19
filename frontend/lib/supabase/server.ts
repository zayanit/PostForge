import { cookies } from "next/headers";
import { createServerClient, type CookieOptions } from "@supabase/ssr";

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;

export function createSupabaseServerClient() {
  if (!supabaseUrl) {
    throw new Error("NEXT_PUBLIC_SUPABASE_URL is required");
  }

  if (!supabaseAnonKey) {
    throw new Error("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY is required");
  }

  const cookieStore = cookies();

  return createServerClient(supabaseUrl, supabaseAnonKey, {
    cookies: {
      getAll() {
        return cookieStore.getAll();
      },
      setAll(cookiesToSet: Array<{ name: string; value: string; options?: CookieOptions }>) {
        try {
          cookiesToSet.forEach(({ name, value, options }) => {
            cookieStore.set({ name, value, ...options });
          });
        } catch {
          // Next.js only permits cookie mutation in Server Actions/Route Handlers.
        }
      },
    },
  });
}
