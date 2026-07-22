import { createBrowserClient } from "@supabase/ssr";

import { getPublicEnv } from "@/lib/runtime-env";

export const supabase = createBrowserClient(
  getPublicEnv("NEXT_PUBLIC_SUPABASE_URL"),
  getPublicEnv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY"),
);
