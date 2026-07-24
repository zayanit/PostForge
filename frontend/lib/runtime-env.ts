export type PublicEnvName =
  | "NEXT_PUBLIC_SUPABASE_URL"
  | "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY"
  | "NEXT_PUBLIC_API_URL";

declare global {
  interface Window {
    __POSTFORGE_PUBLIC_ENV__?: Partial<Record<PublicEnvName, string>>;
  }
}

export function getPublicEnv(name: PublicEnvName): string {
  const value =
    typeof window === "undefined"
      ? process.env[name]
      : window.__POSTFORGE_PUBLIC_ENV__?.[name];

  if (!value) {
    throw new Error(`${name} is required`);
  }

  return value;
}
