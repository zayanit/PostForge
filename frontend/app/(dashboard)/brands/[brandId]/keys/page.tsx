"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { getPublicEnv } from "@/lib/runtime-env";
import { supabase } from "@/lib/supabase/client";

type Provider = "openai" | "gemini";
type CleanupState = "normal" | "cleanup_required";

type Brand = {
  id: string;
  name: string;
  cleanup_state: CleanupState;
};

type ProviderKey = {
  id: string;
  provider: Provider;
  label: string | null;
  key_hint: string;
  is_active: boolean;
  is_valid: boolean | null;
  last_validated_at: string | null;
  last_validation_error: string | null;
  cleanup_state: CleanupState;
  created_at: string;
};

type ErrorResponse = { error?: { code?: string } };
type ValidationOutcome = {
  outcome: "valid" | "invalid" | "temporary";
  attempted_at: string;
  code: string;
  message: string;
  key: ProviderKey;
};

type ValidationFeedback = {
  message: string;
  tone: "success" | "error" | "temporary";
};

const PROVIDERS: Array<{ id: Provider; name: string }> = [
  { id: "openai", name: "OpenAI" },
  { id: "gemini", name: "Gemini" },
];

function addErrorMessage(code?: string) {
  switch (code) {
    case "VALIDATION_ERROR":
      return "Check the key format and label, then try again.";
    case "BRAND_CLEANUP_REQUIRED":
      return "Brand cleanup is required before another key can be added.";
    case "IDEMPOTENCY_KEY_RETIRED":
      return "This request was already completed and deleted. Submit again to create a new key.";
    case "VAULT_UNAVAILABLE":
      return "Secure key storage is unavailable right now.";
    default:
      return "Unable to add the provider key.";
  }
}

function validationLabel(key: ProviderKey) {
  if (key.is_valid === true) return "Valid";
  if (key.is_valid === false) return "Invalid";
  return "Unvalidated";
}

function validationFeedback(outcome: ValidationOutcome): ValidationFeedback {
  if (outcome.outcome === "valid") {
    return { message: "The provider accepted this key.", tone: "success" };
  }
  if (outcome.outcome === "invalid") {
    return { message: "The provider rejected this key.", tone: "error" };
  }

  switch (outcome.code) {
    case "PROVIDER_TIMEOUT":
      return {
        message: "Validation timed out. The saved key status was not changed.",
        tone: "temporary",
      };
    case "VALIDATION_IN_PROGRESS":
      return {
        message: "Validation is already in progress. The saved key status was not changed.",
        tone: "temporary",
      };
    case "VALIDATION_SUPERSEDED":
      return {
        message: "A newer validation replaced this attempt. The latest saved status is shown.",
        tone: "temporary",
      };
    default:
      return {
        message: "The provider could not validate this key right now. The saved key status was not changed.",
        tone: "temporary",
      };
  }
}

function validationErrorMessage(code?: string) {
  switch (code) {
    case "BRAND_CLEANUP_REQUIRED":
      return "Brand cleanup is required before this key can be validated.";
    case "KEY_CLEANUP_REQUIRED":
      return "Key cleanup is required before this key can be validated.";
    case "VAULT_UNAVAILABLE":
      return "Secure key storage is unavailable right now.";
    default:
      return "Unable to validate this key.";
  }
}

export default function ProviderKeysPage() {
  const { brandId } = useParams<{ brandId: string }>();
  const router = useRouter();
  const apiBase = getPublicEnv("NEXT_PUBLIC_API_URL");
  const keyInputRef = useRef<HTMLInputElement>(null);
  const retryIdRef = useRef<string | null>(null);
  const validatingKeyIdsRef = useRef(new Set<string>());
  const [brand, setBrand] = useState<Brand | null>(null);
  const [keys, setKeys] = useState<ProviderKey[]>([]);
  const [provider, setProvider] = useState<Provider>("openai");
  const [label, setLabel] = useState("");
  const [makeActive, setMakeActive] = useState(true);
  const [isLoading, setIsLoading] = useState(true);
  const [isNotFound, setIsNotFound] = useState(false);
  const [isAdding, setIsAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [addError, setAddError] = useState<string | null>(null);
  const [validatingKeyIds, setValidatingKeyIds] = useState<Set<string>>(
    () => new Set()
  );
  const [validationFeedbackByKey, setValidationFeedbackByKey] = useState<
    Record<string, ValidationFeedback>
  >({});

  useEffect(() => {
    let active = true;

    async function loadKeys() {
      setIsLoading(true);
      setError(null);
      setIsNotFound(false);

      try {
        const { data } = await supabase.auth.getSession();
        const session = data.session;
        if (!session) {
          router.push("/login");
          return;
        }

        const path = `${apiBase}/v1/brands/${encodeURIComponent(brandId)}`;
        const headers = { Authorization: `Bearer ${session.access_token}` };
        const [brandResponse, keysResponse] = await Promise.all([
          fetch(path, { headers }),
          fetch(`${path}/keys`, { headers }),
        ]);

        if (brandResponse.status === 404 || keysResponse.status === 404) {
          if (active) setIsNotFound(true);
          return;
        }
        if (!brandResponse.ok || !keysResponse.ok) {
          throw new Error("Provider key metadata was unavailable.");
        }

        const [brandBody, keysBody] = (await Promise.all([
          brandResponse.json(),
          keysResponse.json(),
        ])) as [Brand, { keys: ProviderKey[] }];
        if (active) {
          setBrand(brandBody);
          setKeys(keysBody.keys);
        }
      } catch {
        if (active) setError("Unable to load provider keys.");
      } finally {
        if (active) setIsLoading(false);
      }
    }

    void loadKeys();
    return () => {
      active = false;
    };
  }, [apiBase, brandId, router]);

  function beginNewAttempt() {
    retryIdRef.current = null;
    setAddError(null);
  }

  async function addKey(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const rawKey = keyInputRef.current?.value ?? "";
    if (!rawKey) {
      setAddError("Enter a provider key.");
      return;
    }

    const idempotencyKey = retryIdRef.current ?? crypto.randomUUID();
    setAddError(null);
    setIsAdding(true);

    try {
      const { data } = await supabase.auth.getSession();
      const session = data.session;
      if (!session) {
        router.push("/login");
        return;
      }

      const response = await fetch(
        `${apiBase}/v1/brands/${encodeURIComponent(brandId)}/keys`,
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${session.access_token}`,
            "Content-Type": "application/json",
            "Idempotency-Key": idempotencyKey,
          },
          body: JSON.stringify({
            provider,
            key: rawKey,
            label: label || null,
            make_active: makeActive,
          }),
        }
      );

      const body = (await response.json().catch(() => null)) as
        | ProviderKey
        | ErrorResponse
        | null;
      if (!response.ok) {
        retryIdRef.current = response.status >= 500 ? idempotencyKey : null;
        setAddError(addErrorMessage((body as ErrorResponse | null)?.error?.code));
        return;
      }

      retryIdRef.current = null;
      const addedKey = body as ProviderKey;
      setKeys((current) => [
        addedKey,
        ...current.map((key) =>
          addedKey.is_active && key.provider === addedKey.provider
            ? { ...key, is_active: false }
            : key
        ),
      ]);
      if (keyInputRef.current) keyInputRef.current.value = "";
      setLabel("");
      setMakeActive(true);
    } catch {
      retryIdRef.current = idempotencyKey;
      setAddError(
        "The request outcome is unknown. Retry this unchanged submission to reconcile it."
      );
    } finally {
      setIsAdding(false);
    }
  }

  async function validateKey(keyId: string) {
    if (validatingKeyIdsRef.current.has(keyId)) return;

    validatingKeyIdsRef.current.add(keyId);
    setValidatingKeyIds((current) => new Set(current).add(keyId));
    setValidationFeedbackByKey((current) => {
      const next = { ...current };
      delete next[keyId];
      return next;
    });

    try {
      const { data } = await supabase.auth.getSession();
      const session = data.session;
      if (!session) {
        router.push("/login");
        return;
      }

      const response = await fetch(
        `${apiBase}/v1/brands/${encodeURIComponent(brandId)}/keys/${encodeURIComponent(keyId)}/validate`,
        {
          method: "POST",
          headers: { Authorization: `Bearer ${session.access_token}` },
        }
      );
      const body = (await response.json().catch(() => null)) as
        | ValidationOutcome
        | ErrorResponse
        | null;
      if (!response.ok) {
        setValidationFeedbackByKey((current) => ({
          ...current,
          [keyId]: {
            message: validationErrorMessage(
              (body as ErrorResponse | null)?.error?.code
            ),
            tone: "error",
          },
        }));
        return;
      }

      const outcome = body as ValidationOutcome;
      setKeys((current) =>
        current.map((key) => (key.id === keyId ? outcome.key : key))
      );
      setValidationFeedbackByKey((current) => ({
        ...current,
        [keyId]: validationFeedback(outcome),
      }));
    } catch {
      setValidationFeedbackByKey((current) => ({
        ...current,
        [keyId]: {
          message: "Unable to validate this key. Refresh its status before trying again.",
          tone: "error",
        },
      }));
    } finally {
      validatingKeyIdsRef.current.delete(keyId);
      setValidatingKeyIds((current) => {
        const next = new Set(current);
        next.delete(keyId);
        return next;
      });
    }
  }

  if (isLoading) {
    return <p className="mx-auto max-w-5xl text-sm text-gray-600">Loading provider keys...</p>;
  }

  if (isNotFound) {
    return (
      <section className="mx-auto max-w-xl rounded-2xl border p-10 text-center">
        <h1 className="text-2xl font-semibold">Brand not found</h1>
        <p className="mt-2 text-sm text-gray-600">
          This brand does not exist or is not available to you.
        </p>
        <Link className="mt-5 inline-block rounded-md border px-4 py-2 text-sm" href="/brands">
          Back to brands
        </Link>
      </section>
    );
  }

  if (error || !brand) {
    return <p className="mx-auto max-w-5xl text-sm text-red-600">{error ?? "Unable to load provider keys."}</p>;
  }

  const providerName = PROVIDERS.find((item) => item.id === provider)?.name ?? provider;
  const providerKeys = keys.filter((key) => key.provider === provider);
  const cleanupRequired = brand.cleanup_state === "cleanup_required";

  return (
    <section className="mx-auto max-w-5xl space-y-8">
      <div className="space-y-4">
        <Link className="text-sm text-gray-600 hover:text-black" href={`/brands/${brand.id}`}>
          Back to {brand.name}
        </Link>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-sm font-medium uppercase tracking-wider text-gray-500">Provider setup</p>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight">Provider keys</h1>
            <p className="mt-2 text-sm text-gray-600">
              Keys are stored securely. Only labels and masked hints are shown after submission.
            </p>
          </div>
          {cleanupRequired ? (
            <span className="w-fit rounded-full bg-amber-100 px-3 py-1 text-xs font-medium text-amber-900">
              Brand cleanup required
            </span>
          ) : null}
        </div>
      </div>

      <nav className="flex gap-1 rounded-lg bg-gray-100 p-1" aria-label="Provider groups" role="tablist">
        {PROVIDERS.map((item) => (
          <button
            className={`flex-1 rounded-md px-4 py-2 text-sm font-medium transition ${
              provider === item.id ? "bg-white shadow-sm" : "text-gray-600 hover:text-black"
            }`}
            key={item.id}
            type="button"
            role="tab"
            aria-selected={provider === item.id}
            onClick={() => {
              setProvider(item.id);
              beginNewAttempt();
            }}
          >
            {item.name}
          </button>
        ))}
      </nav>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="space-y-4" role="tabpanel" aria-label={`${providerName} keys`}>
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold">{providerName} keys</h2>
            <span className="text-xs text-gray-500">{providerKeys.length} saved</span>
          </div>
          {providerKeys.length === 0 ? (
            <div className="rounded-xl border border-dashed p-8 text-center text-sm text-gray-600">
              No {providerName} keys have been added.
            </div>
          ) : (
            providerKeys.map((key) => {
              const isValidating = validatingKeyIds.has(key.id);
              const feedback = validationFeedbackByKey[key.id];
              const validationDisabled =
                isValidating ||
                cleanupRequired ||
                key.cleanup_state === "cleanup_required";

              return (
                <article className="rounded-xl border bg-white p-5 shadow-sm" key={key.id}>
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <h3 className="font-semibold">{key.label || `${providerName} key`}</h3>
                      <p className="mt-1 font-mono text-sm text-gray-600">{key.key_hint}</p>
                    </div>
                    <div className="flex flex-wrap justify-end gap-2">
                      <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${key.is_active ? "bg-emerald-100 text-emerald-800" : "bg-gray-100 text-gray-700"}`}>
                        {key.is_active ? "Active" : "Inactive"}
                      </span>
                      <span className="rounded-full bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-800">
                        {validationLabel(key)}
                      </span>
                      {key.cleanup_state === "cleanup_required" ? (
                        <span className="rounded-full bg-amber-100 px-2.5 py-1 text-xs font-medium text-amber-900">
                          Cleanup required
                        </span>
                      ) : null}
                    </div>
                  </div>
                  <div className="mt-5 flex flex-col gap-3 border-t pt-4 sm:flex-row sm:items-end sm:justify-between">
                    <div className="text-xs text-gray-500">
                      <p>Added {new Date(key.created_at).toLocaleDateString()}</p>
                      <p className="mt-1">
                        {key.last_validated_at
                          ? `Last validated ${new Date(key.last_validated_at).toLocaleString()}`
                          : "Not yet validated"}
                      </p>
                    </div>
                    <button
                      className="rounded-md border px-3 py-2 text-sm font-medium hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
                      type="button"
                      disabled={validationDisabled}
                      onClick={() => void validateKey(key.id)}
                    >
                      {isValidating ? "Validating..." : "Validate key"}
                    </button>
                  </div>
                  {feedback ? (
                    <p
                      className={`mt-3 text-sm ${
                        feedback.tone === "success"
                          ? "text-emerald-700"
                          : feedback.tone === "error"
                            ? "text-red-600"
                            : "text-amber-700"
                      }`}
                      role="status"
                    >
                      {feedback.message}
                    </p>
                  ) : null}
                </article>
              );
            })
          )}
        </div>

        <form className="h-fit space-y-5 rounded-xl border bg-white p-6 shadow-sm" onSubmit={addKey} noValidate>
          <div>
            <h2 className="font-semibold">Add {providerName} key</h2>
            <p className="mt-1 text-sm text-gray-600">The credential cannot be revealed after it is stored.</p>
          </div>
          <label className="block space-y-2">
            <span className="text-sm font-medium">Label <span className="font-normal text-gray-500">(optional)</span></span>
            <input
              className="w-full rounded-md border px-3 py-2 text-sm outline-none focus:border-black"
              type="text"
              maxLength={100}
              value={label}
              disabled={isAdding || cleanupRequired}
              onChange={(event) => {
                setLabel(event.target.value);
                beginNewAttempt();
              }}
            />
          </label>
          <label className="block space-y-2">
            <span className="text-sm font-medium">API key</span>
            <input
              ref={keyInputRef}
              className="w-full rounded-md border px-3 py-2 text-sm outline-none focus:border-black"
              type="password"
              autoComplete="new-password"
              disabled={isAdding || cleanupRequired}
              onChange={beginNewAttempt}
            />
          </label>
          <label className="flex items-start gap-3 text-sm">
            <input
              className="mt-1"
              type="checkbox"
              checked={makeActive}
              disabled={isAdding || cleanupRequired}
              onChange={(event) => {
                setMakeActive(event.target.checked);
                beginNewAttempt();
              }}
            />
            <span><span className="font-medium">Make active</span><span className="mt-0.5 block text-gray-500">Future {providerName} work will use this key.</span></span>
          </label>
          {addError ? <p className="text-sm text-red-600" role="alert">{addError}</p> : null}
          <button
            className="w-full rounded-md bg-black px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
            type="submit"
            disabled={isAdding || cleanupRequired}
          >
            {isAdding ? "Storing securely..." : `Add ${providerName} key`}
          </button>
        </form>
      </div>
    </section>
  );
}
