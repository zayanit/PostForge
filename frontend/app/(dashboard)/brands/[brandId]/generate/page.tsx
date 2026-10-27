"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";
import GenerationResult from "@/components/generation-result";
import {
  activeGeneration,
  generationApi,
  type Generation,
  type History,
  type Preset,
} from "@/lib/generations";

export default function GeneratePage() {
  const { brandId } = useParams<{ brandId: string }>();
  const [brand, setBrand] = useState<{
    name: string;
    kit_status: string;
    cleanup_state: string;
  } | null>(null);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [prompt, setPrompt] = useState("");
  const [preset, setPreset] = useState("");
  const [generation, setGeneration] = useState<Generation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const submission = useRef<{ body: string; key: string } | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setGeneration(null);
    setBrand(null);
    setError(null);
    submission.current = null;
    async function load() {
      try {
        const [loadedBrand, catalog] = await Promise.all([
          generationApi<{
            name: string;
            kit_status: string;
            cleanup_state: string;
          }>(`/${brandId}`),
          generationApi<{ presets: Preset[] }>("/generation-presets"),
        ]);
        const id = new URL(window.location.href).searchParams.get("generation");
        const previous = id
          ? await generationApi<Generation>(`/${brandId}/generations/${id}`)
          : ((
              await generationApi<History>(`/${brandId}/generations?per_page=1`)
            ).generations[0] ?? null);
        if (active) {
          setBrand(loadedBrand);
          setPresets(catalog.presets);
          setGeneration(previous);
        }
      } catch (cause) {
        if (active)
          setError(
            cause instanceof Error
              ? cause.message
              : "Unable to load generation settings."
          );
      } finally {
        if (active) setLoading(false);
      }
    }
    void load();
    return () => {
      active = false;
    };
  }, [brandId]);

  useEffect(() => {
    if (!generation) return;
    let active = true;
    const id = generation.id;
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      try {
        const current = await generationApi<Generation>(
          `/${brandId}/generations/${id}`
        );
        if (active) {
          setGeneration(current);
          setError(null);
          timer = setTimeout(
            refresh,
            activeGeneration(current) ? 2000 : 240000
          );
        }
      } catch (cause) {
        if (active) {
          setError(
            cause instanceof Error
              ? cause.message
              : "Unable to refresh this image."
          );
          timer = setTimeout(refresh, 10000);
        }
      }
    }
    timer = setTimeout(refresh, activeGeneration(generation) ? 2000 : 240000);
    return () => {
      active = false;
      clearTimeout(timer);
    };
    // Refresh continuously for this ID without resetting polling on every response.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [brandId, generation?.id]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (submitting || !preset || prompt.trim().length < 3) return;
    setError(null);
    setSubmitting(true);
    const body = JSON.stringify({
      prompt: prompt.trim(),
      platform_preset: preset,
    });
    if (submission.current?.body !== body)
      submission.current = { body, key: crypto.randomUUID() };
    try {
      const result = await generationApi<Generation>(`/${brandId}/generate`, {
        method: "POST",
        headers: { "Idempotency-Key": submission.current.key },
        body,
      });
      setGeneration(result);
      submission.current = null;
      window.history.replaceState(
        null,
        "",
        `${window.location.pathname}?generation=${result.id}`
      );
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Submission failed. You can safely retry the same submission."
      );
    } finally {
      setSubmitting(false);
    }
  }

  if (loading)
    return (
      <p role="status" className="mx-auto max-w-3xl">
        Loading generation settings…
      </p>
    );
  const busy =
    submitting || Boolean(generation && activeGeneration(generation));
  return (
    <section className="mx-auto max-w-3xl space-y-6">
      <nav className="flex gap-4 text-sm">
        <Link href={`/brands/${brandId}`}>Back to brand</Link>
        <Link href={`/brands/${brandId}/history`}>History</Link>
      </nav>
      <div>
        <h1 className="text-2xl font-semibold">
          Generate an image{brand ? ` for ${brand.name}` : ""}
        </h1>
        <p className="mt-2 text-sm text-gray-600">
          OpenAI · gpt-image-2 · medium quality · one PNG per request. Uses your
          own OpenAI account.
        </p>
      </div>
      {brand?.kit_status !== "complete" && brand ? (
        <p className="rounded-lg bg-amber-50 p-4 text-sm">
          You can generate now with your saved brand context.{" "}
          <Link className="underline" href={`/brands/${brandId}/kit`}>
            Complete your Brand Kit
          </Link>{" "}
          for more consistent results.
        </p>
      ) : null}
      {brand?.cleanup_state === "cleanup_required" ? (
        <p role="alert">
          Brand cleanup is in progress. Return to the brand to retry deletion.
        </p>
      ) : null}
      <form className="space-y-5 rounded-2xl border p-6" onSubmit={submit}>
        <label className="block text-sm font-medium">
          Image prompt
          <textarea
            className="mt-2 block min-h-36 w-full rounded-md border p-3"
            required
            minLength={3}
            maxLength={4000}
            value={prompt}
            disabled={busy}
            onChange={(event) => setPrompt(event.target.value)}
          />
        </label>
        <p className="text-xs text-gray-500">
          {prompt.length} / 4,000 characters
        </p>
        <label className="block text-sm font-medium">
          Platform preset
          <select
            className="mt-2 block w-full rounded-md border p-3"
            required
            value={preset}
            disabled={busy}
            onChange={(event) => setPreset(event.target.value)}
          >
            <option value="">Choose a platform preset</option>
            {presets.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label} — {item.width} × {item.height}
              </option>
            ))}
          </select>
        </label>
        <p className="text-sm text-gray-600">
          Images are center-cropped and resized to your selected dimensions.
          Keep important content near the center.
        </p>
        <div className="flex flex-wrap items-center gap-4">
          <button
            className="rounded-md bg-black px-4 py-2 text-sm text-white disabled:opacity-50"
            disabled={
              !brand ||
              brand.cleanup_state !== "normal" ||
              busy ||
              !preset ||
              prompt.trim().length < 3
            }
          >
            {submitting
              ? "Submitting…"
              : busy
                ? "Image in progress"
                : "Generate image"}
          </button>
          <Link className="text-sm underline" href={`/brands/${brandId}/keys`}>
            Manage provider keys
          </Link>
        </div>
      </form>
      {error ? (
        <p className="text-sm text-red-700" role="alert">
          {error}
        </p>
      ) : null}
      {generation ? <GenerationResult generation={generation} /> : null}
    </section>
  );
}
