import { getPublicEnv } from "@/lib/runtime-env";
import { supabase } from "@/lib/supabase/client";

export type Generation = {
  id: string;
  brand_id: string;
  prompt: string;
  provider: "openai";
  model: string;
  platform_preset: string;
  width: number;
  height: number;
  status: "pending" | "processing" | "succeeded" | "failed";
  error_code: string | null;
  image_url: string | null;
  cleanup_required: boolean;
  created_at: string;
  completed_at: string | null;
};

export type Preset = {
  id: string;
  label: string;
  width: number;
  height: number;
};
export type History = {
  generations: Generation[];
  page: number;
  per_page: number;
  total: number;
};

const MESSAGES: Record<string, string> = {
  OPENAI_KEY_REQUIRED:
    "Add or activate an OpenAI key in this brand’s provider settings.",
  OPENAI_KEY_REJECTED:
    "OpenAI rejected this key. Check your provider settings and account access.",
  PROVIDER_RATE_LIMITED:
    "OpenAI is rate limiting requests. Try a new generation later.",
  PROVIDER_REJECTED:
    "OpenAI could not accept this request. Review your prompt before trying again.",
  PROVIDER_UNAVAILABLE:
    "OpenAI was unavailable. This attempt was not automatically repeated.",
  PROVIDER_TIMEOUT:
    "OpenAI did not respond in time. This attempt was not automatically repeated.",
  GENERATION_INTERRUPTED:
    "Processing was interrupted. No image was recovered and the paid request was not repeated.",
  INVALID_PROVIDER_IMAGE:
    "The provider returned an image we could not process.",
  GENERATION_PROCESSING:
    "This image is still processing. Wait before deleting it.",
  GENERATION_ASSET_BUSY: "Image storage is busy. Try again shortly.",
  IDEMPOTENCY_CONFLICT:
    "This submission ID was already used for different input. Reload before submitting again.",
  STORAGE_UNAVAILABLE:
    "Image storage is unavailable. Try loading the page again shortly.",
  BRAND_CLEANUP_REQUIRED:
    "Brand cleanup is in progress. Return to the brand to retry deletion.",
  GENERATION_NOT_FOUND: "Brand or generation not found.",
  UNAUTHORIZED: "Your session has expired. Sign in again.",
};

export function generationMessage(code: string | null) {
  return (
    MESSAGES[code ?? ""] ??
    "The request could not be completed. Please try again."
  );
}

export async function generationApi<T>(
  path: string,
  init: RequestInit = {}
): Promise<T> {
  const { data } = await supabase.auth.getSession();
  if (!data.session) throw new Error(MESSAGES.UNAUTHORIZED);
  const response = await fetch(
    `${getPublicEnv("NEXT_PUBLIC_API_URL")}/v1/brands${path}`,
    {
      ...init,
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${data.session.access_token}`,
        ...init.headers,
      },
    }
  );
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(generationMessage(body?.error?.code));
  }
  return response.status === 204 ? (undefined as T) : response.json();
}

export async function downloadGeneration(
  brandId: string,
  generationId: string
) {
  const generation = await generationApi<Generation>(
    `/${brandId}/generations/${generationId}`
  );
  if (!generation.image_url)
    throw new Error("This image is not available for download.");
  const response = await fetch(generation.image_url, { cache: "no-store" });
  if (!response.ok) throw new Error("Download failed. Please try again.");
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = `postforge-${generation.platform_preset}-${generation.id}.png`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function activeGeneration(generation: Generation) {
  return generation.status === "pending" || generation.status === "processing";
}
