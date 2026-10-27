/* eslint-disable @next/next/no-img-element */
"use client";

import Link from "next/link";
import { useState } from "react";
import {
  downloadGeneration,
  generationMessage,
  type Generation,
} from "@/lib/generations";

export default function GenerationResult({
  generation,
}: {
  generation: Generation;
}) {
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  const status = generation.cleanup_required
    ? "Cleanup required"
    : {
        pending: "Queued",
        processing: "Processing",
        succeeded: "Ready",
        failed: "Failed",
      }[generation.status];
  return (
    <article className="space-y-4 rounded-2xl border p-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span
          className="rounded-full bg-gray-100 px-3 py-1 text-sm"
          role="status"
        >
          {status}
        </span>
        <span className="text-xs text-gray-600">
          OpenAI · {generation.width} × {generation.height} · PNG
        </span>
      </div>
      {generation.image_url && !generation.cleanup_required ? (
        <a
          href={generation.image_url}
          target="_blank"
          rel="noreferrer"
          aria-label="Open full image"
        >
          <img
            className="mx-auto max-h-[36rem] max-w-full rounded-lg object-contain"
            src={generation.image_url}
            alt={generation.prompt}
          />
        </a>
      ) : null}
      {generation.status === "pending" || generation.status === "processing" ? (
        <p className="text-sm text-gray-600">
          You can leave this page. Your image will remain in this brand’s
          history.
        </p>
      ) : null}
      {generation.status === "failed" ? (
        <p role="alert" className="text-sm text-red-700">
          {generationMessage(generation.error_code)}
        </p>
      ) : null}
      {generation.cleanup_required ? (
        <p className="text-sm text-amber-800">
          Deletion did not finish. Retry deletion from history.
        </p>
      ) : null}
      <p className="whitespace-pre-wrap break-words text-sm">
        {generation.prompt}
      </p>
      <p className="text-xs text-gray-500">
        {generation.platform_preset.replaceAll("_", " ")} ·{" "}
        {new Date(generation.created_at).toLocaleString()}
      </p>
      <div className="flex flex-wrap gap-3">
        {generation.image_url && !generation.cleanup_required ? (
          <button
            className="rounded-md bg-black px-4 py-2 text-sm text-white disabled:opacity-50"
            disabled={downloading}
            onClick={async () => {
              setDownloading(true);
              setError(null);
              try {
                await downloadGeneration(generation.brand_id, generation.id);
              } catch (cause) {
                setError(
                  cause instanceof Error ? cause.message : "Download failed."
                );
              } finally {
                setDownloading(false);
              }
            }}
          >
            {downloading ? "Downloading…" : "Download PNG"}
          </button>
        ) : null}
        {generation.error_code?.startsWith("OPENAI_KEY") ? (
          <Link
            className="rounded-md border px-4 py-2 text-sm"
            href={`/brands/${generation.brand_id}/keys`}
          >
            Manage provider keys
          </Link>
        ) : null}
      </div>
      {error ? (
        <p role="alert" className="text-sm text-red-700">
          {error}
        </p>
      ) : null}
    </article>
  );
}
