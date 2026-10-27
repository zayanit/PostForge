"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import GenerationResult from "@/components/generation-result";
import {
  activeGeneration,
  generationApi,
  type Generation,
  type History,
} from "@/lib/generations";

export default function HistoryPage() {
  const { brandId } = useParams<{ brandId: string }>();
  const [history, setHistory] = useState<History | null>(null);
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<Generation | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [revision, setRevision] = useState(0);
  const dialog = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    if (confirm) dialog.current?.showModal();
    else dialog.current?.close();
  }, [confirm]);

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    setHistory(null);
    async function refresh() {
      try {
        const result = await generationApi<History>(
          `/${brandId}/generations?page=${page}${status ? `&status=${status}` : ""}`
        );
        if (active) {
          if (page > 1 && result.generations.length === 0) {
            setPage(page - 1);
            return;
          }
          setHistory(result);
          setError(null);
          timer = setTimeout(
            refresh,
            result.generations.some(activeGeneration) ? 2000 : 240000
          );
        }
      } catch (cause) {
        if (active) {
          setError(
            cause instanceof Error ? cause.message : "Unable to load history."
          );
          timer = setTimeout(refresh, 10000);
        }
      }
    }
    void refresh();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [brandId, page, status, revision]);

  async function remove() {
    if (!confirm) return;
    setDeleting(true);
    setError(null);
    try {
      await generationApi(`/${brandId}/generations/${confirm.id}`, {
        method: "DELETE",
      });
      setConfirm(null);
      setRevision((value) => value + 1);
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Deletion failed. Please retry."
      );
    } finally {
      setDeleting(false);
    }
  }

  return (
    <section className="mx-auto max-w-5xl space-y-6">
      <nav className="flex gap-4 text-sm">
        <Link href={`/brands/${brandId}`}>Back to brand</Link>
        <Link href={`/brands/${brandId}/generate`}>Generate an image</Link>
      </nav>
      <h1 className="text-2xl font-semibold">Image history</h1>
      <label className="block text-sm">
        Status
        <select
          className="ml-3 rounded-md border p-2"
          value={status}
          onChange={(event) => {
            setStatus(event.target.value);
            setPage(1);
          }}
        >
          <option value="">All statuses</option>
          <option value="pending">Queued</option>
          <option value="processing">Processing</option>
          <option value="succeeded">Ready</option>
          <option value="failed">Failed</option>
        </select>
      </label>
      {error ? (
        <p role="alert" className="text-sm text-red-700">
          {error}
        </p>
      ) : null}
      {!history && !error ? <p role="status">Loading history…</p> : null}
      {history?.total === 0 ? (
        <p>
          No images yet.{" "}
          <Link className="underline" href={`/brands/${brandId}/generate`}>
            Generate your first image.
          </Link>
        </p>
      ) : null}
      <div className="grid gap-6 md:grid-cols-2">
        {history?.generations.map((generation) => (
          <div className="space-y-2" key={generation.id}>
            <GenerationResult generation={generation} />
            <button
              className="rounded-md border border-red-200 px-4 py-2 text-sm text-red-700 disabled:opacity-50"
              disabled={generation.status === "processing" || deleting}
              onClick={() => setConfirm(generation)}
            >
              {generation.cleanup_required ? "Retry deletion" : "Delete image"}
            </button>
          </div>
        ))}
      </div>
      {history && history.total > 20 ? (
        <nav
          aria-label="History pagination"
          className="flex items-center gap-4"
        >
          <button
            className="rounded-md border p-2 disabled:opacity-50"
            disabled={page === 1}
            onClick={() => setPage((value) => value - 1)}
          >
            Previous page
          </button>
          <span>
            Page {page} of {Math.ceil(history.total / 20)}
          </span>
          <button
            className="rounded-md border p-2 disabled:opacity-50"
            disabled={page * 20 >= history.total}
            onClick={() => setPage((value) => value + 1)}
          >
            Next page
          </button>
        </nav>
      ) : null}
      {confirm ? (
        <dialog
          ref={dialog}
          aria-labelledby="delete-image-title"
          className="m-auto max-w-md rounded-xl bg-white p-0 backdrop:bg-black/40"
          onCancel={(event) => {
            if (deleting) event.preventDefault();
            else setConfirm(null);
          }}
        >
          <div className="max-w-md space-y-4 rounded-xl bg-white p-6">
            <h2 id="delete-image-title" className="text-lg font-semibold">
              Permanently delete this image?
            </h2>
            <p className="text-sm">
              This removes the image and its history record. It cannot be
              undone.
            </p>
            <div className="flex gap-3">
              <button
                autoFocus
                className="rounded-md border px-4 py-2"
                disabled={deleting}
                onClick={() => setConfirm(null)}
              >
                Cancel
              </button>
              <button
                className="rounded-md bg-red-700 px-4 py-2 text-white disabled:opacity-50"
                disabled={deleting}
                onClick={remove}
              >
                {deleting ? "Deleting…" : "Delete permanently"}
              </button>
            </div>
            {error ? (
              <p role="alert" className="text-sm text-red-700">
                {error}
              </p>
            ) : null}
          </div>
        </dialog>
      ) : null}
    </section>
  );
}
