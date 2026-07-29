"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { getPublicEnv } from "@/lib/runtime-env";
import { supabase } from "@/lib/supabase/client";

type Tone = "formal" | "casual" | "playful" | "professional" | "friendly";
type KitStatus = "not_started" | "in_progress" | "complete";

type FormValues = {
  name: string;
  tagline: string;
  tone: Tone | "";
  audience: string;
  colors: string;
  avoidWords: string;
};

type KitResponse = {
  brand_id: string;
  brand_name: string;
  answers: {
    tagline: string | null;
    tone: Tone | null;
    audience: string | null;
    colors: string[];
    avoid_words: string | null;
  };
  summary: string | null;
  status: KitStatus;
  completed_at: string | null;
  updated_at: string | null;
};

type ApiError = { error?: { message?: string } };

const STEPS = ["Name", "Tagline", "Tone", "Audience", "Colors", "Avoid words"] as const;

const EMPTY_FORM: FormValues = {
  name: "",
  tagline: "",
  tone: "",
  audience: "",
  colors: "",
  avoidWords: "",
};

function colorsFromInput(value: string) {
  return value
    .split(",")
    .map((color) => color.trim())
    .filter(Boolean);
}

function validateStep(step: number, values: FormValues): string | null {
  switch (step) {
    case 0:
      return values.name.trim().length < 2 || values.name.trim().length > 120
        ? "Name must be between 2 and 120 characters."
        : null;
    case 1:
      return values.tagline.length > 160 ? "Tagline must be 160 characters or fewer." : null;
    case 2:
      return values.tone ? null : "Choose a tone.";
    case 3:
      return values.audience.trim().length < 2 || values.audience.trim().length > 500
        ? "Audience must be between 2 and 500 characters."
        : null;
    case 4: {
      const colors = colorsFromInput(values.colors);
      if (colors.length < 1 || colors.length > 3) {
        return "Enter between 1 and 3 colors, separated by commas.";
      }
      if (colors.some((color) => !/^#[0-9a-fA-F]{6}$/.test(color))) {
        return "Colors must use the #RRGGBB format.";
      }
      return null;
    }
    case 5:
      return null;
    default:
      return null;
  }
}

function apiErrorMessage(body: ApiError | null, fallback: string) {
  return body?.error?.message ?? fallback;
}

export default function BrandKitPage() {
  const { brandId } = useParams<{ brandId: string }>();
  const router = useRouter();
  const apiBase = getPublicEnv("NEXT_PUBLIC_API_URL");
  const [values, setValues] = useState<FormValues>(EMPTY_FORM);
  const [step, setStep] = useState(0);
  const [status, setStatus] = useState<KitStatus>("not_started");
  const [summary, setSummary] = useState<string | null>(null);
  const [brandName, setBrandName] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    async function loadKit() {
      try {
        const { data } = await supabase.auth.getSession();
        const session = data.session;
        if (!session) {
          router.push("/login");
          return;
        }

        const response = await fetch(
          `${apiBase}/v1/brands/${encodeURIComponent(brandId)}/kit`,
          { headers: { Authorization: `Bearer ${session.access_token}` } }
        );
        const body = (await response.json().catch(() => null)) as KitResponse | ApiError | null;
        if (!response.ok) {
          throw new Error(apiErrorMessage(body as ApiError | null, "Unable to load the Brand Kit."));
        }

        const kit = body as KitResponse;
        if (active) {
          setStatus(kit.status);
          setBrandName(kit.brand_name);
          setValues({
            name: kit.brand_name,
            tagline: kit.answers.tagline ?? "",
            tone: kit.answers.tone ?? "",
            audience: kit.answers.audience ?? "",
            colors: kit.answers.colors.join(", "),
            avoidWords: kit.answers.avoid_words ?? "",
          });
          setSummary(kit.summary);
        }
      } catch (loadError) {
        if (active) {
          setError(loadError instanceof Error ? loadError.message : "Unable to load the Brand Kit.");
        }
      } finally {
        if (active) setIsLoading(false);
      }
    }

    void loadKit();
    return () => {
      active = false;
    };
  }, [apiBase, brandId, router]);

  function updateValue(field: keyof FormValues, value: string) {
    setValues((current) => ({ ...current, [field]: value }));
    setValidationError(null);
    setError(null);
  }

  function nextStep() {
    const message = validateStep(step, values);
    if (message) {
      setValidationError(message);
      return;
    }
    setValidationError(null);
    setStep((current) => Math.min(current + 1, STEPS.length - 1));
  }

  function previousStep() {
    setValidationError(null);
    setStep((current) => Math.max(current - 1, 0));
  }

  async function saveKit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    for (let index = 0; index < STEPS.length; index += 1) {
      const message = validateStep(index, values);
      if (message) {
        setStep(index);
        setValidationError(message);
        return;
      }
    }

    setValidationError(null);
    setError(null);
    setIsSaving(true);
    try {
      const { data } = await supabase.auth.getSession();
      const session = data.session;
      if (!session) {
        router.push("/login");
        return;
      }

      const response = await fetch(
        `${apiBase}/v1/brands/${encodeURIComponent(brandId)}/kit`,
        {
          method: "PUT",
          headers: {
            Authorization: `Bearer ${session.access_token}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            name: values.name.trim(),
            answers: {
              tagline: values.tagline.trim() || null,
              tone: values.tone,
              audience: values.audience.trim(),
              colors: colorsFromInput(values.colors).map((color) => color.toUpperCase()),
              avoid_words: values.avoidWords.trim() || null,
            },
          }),
        }
      );
      const body = (await response.json().catch(() => null)) as KitResponse | ApiError | null;
      if (!response.ok) {
        setError(apiErrorMessage(body as ApiError | null, "Unable to save the Brand Kit."));
        return;
      }

      const kit = body as KitResponse;
      setStatus(kit.status);
      setBrandName(kit.brand_name);
      setSummary(kit.summary);
    } catch {
      setError("Unable to save the Brand Kit. Try again.");
    } finally {
      setIsSaving(false);
    }
  }

  if (isLoading) {
    return <p className="mx-auto max-w-3xl text-sm text-gray-600">Loading Brand Kit...</p>;
  }

  if (error && !brandName) {
    return <p className="mx-auto max-w-3xl text-sm text-red-600">{error}</p>;
  }

  if (status === "complete" && summary) {
    return (
      <section className="mx-auto max-w-3xl space-y-8">
        <Link className="text-sm text-gray-600 hover:text-black" href={`/brands/${brandId}`}>
          Back to {brandName}
        </Link>
        <div className="rounded-2xl border p-8">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-sm font-medium uppercase tracking-wider text-gray-500">Brand Kit</p>
              <h1 className="mt-2 text-3xl font-semibold tracking-tight">Complete</h1>
            </div>
            <span className="rounded-full bg-emerald-100 px-3 py-1 text-xs font-medium text-emerald-800">
              Complete
            </span>
          </div>
          <pre className="mt-6 whitespace-pre-wrap border-t pt-6 font-sans text-sm leading-6 text-gray-700">
            {summary}
          </pre>
          <button
            className="mt-6 rounded-md border px-4 py-2 text-sm font-medium hover:border-gray-400"
            type="button"
            onClick={() => setSummary(null)}
          >
            Edit Brand Kit
          </button>
        </div>
      </section>
    );
  }

  const fieldProps = {
    value: values,
    updateValue,
    disabled: isSaving,
  };

  return (
    <section className="mx-auto max-w-2xl space-y-8">
      <div>
        <Link className="text-sm text-gray-600 hover:text-black" href={`/brands/${brandId}`}>
          Back to brand
        </Link>
        <p className="mt-6 text-sm font-medium uppercase tracking-wider text-gray-500">Brand Kit</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight">Build your brand identity</h1>
        <p className="mt-2 text-sm text-gray-600">Step {step + 1} of {STEPS.length}</p>
      </div>

      <div className="flex gap-1" aria-label="Brand Kit steps">
        {STEPS.map((stepName, index) => (
          <div
            className={`h-1 flex-1 rounded-full ${index <= step ? "bg-black" : "bg-gray-200"}`}
            key={stepName}
            aria-label={`${stepName}${index === step ? ", current step" : ""}`}
          />
        ))}
      </div>

      <form className="rounded-2xl border p-8" onSubmit={saveKit} noValidate>
        <h2 className="text-2xl font-semibold">{STEPS[step]}</h2>
        <div className="mt-6">
          {step === 0 ? (
            <label className="block space-y-2">
              <span className="text-sm font-medium">Brand name</span>
              <input className="w-full rounded-md border px-3 py-2 text-sm outline-none focus:border-black" type="text" value={fieldProps.value.name} disabled={fieldProps.disabled} onChange={(event) => fieldProps.updateValue("name", event.target.value)} />
            </label>
          ) : null}
          {step === 1 ? (
            <label className="block space-y-2">
              <span className="text-sm font-medium">Tagline <span className="font-normal text-gray-500">(optional)</span></span>
              <input className="w-full rounded-md border px-3 py-2 text-sm outline-none focus:border-black" type="text" value={fieldProps.value.tagline} disabled={fieldProps.disabled} onChange={(event) => fieldProps.updateValue("tagline", event.target.value)} />
            </label>
          ) : null}
          {step === 2 ? (
            <label className="block space-y-2">
              <span className="text-sm font-medium">Tone</span>
              <select className="w-full rounded-md border bg-white px-3 py-2 text-sm outline-none focus:border-black" value={fieldProps.value.tone} disabled={fieldProps.disabled} onChange={(event) => fieldProps.updateValue("tone", event.target.value)}>
                <option value="">Choose a tone</option>
                <option value="formal">Formal</option>
                <option value="casual">Casual</option>
                <option value="playful">Playful</option>
                <option value="professional">Professional</option>
                <option value="friendly">Friendly</option>
              </select>
            </label>
          ) : null}
          {step === 3 ? (
            <label className="block space-y-2">
              <span className="text-sm font-medium">Audience</span>
              <textarea className="min-h-28 w-full rounded-md border px-3 py-2 text-sm outline-none focus:border-black" value={fieldProps.value.audience} disabled={fieldProps.disabled} onChange={(event) => fieldProps.updateValue("audience", event.target.value)} />
            </label>
          ) : null}
          {step === 4 ? (
            <label className="block space-y-2">
              <span className="text-sm font-medium">Colors</span>
              <input className="w-full rounded-md border px-3 py-2 text-sm outline-none focus:border-black" type="text" placeholder="#FF5733, #3498DB" value={fieldProps.value.colors} disabled={fieldProps.disabled} onChange={(event) => fieldProps.updateValue("colors", event.target.value)} />
              <span className="block text-xs text-gray-500">Enter 1 to 3 six-digit hex colors separated by commas.</span>
            </label>
          ) : null}
          {step === 5 ? (
            <label className="block space-y-2">
              <span className="text-sm font-medium">Avoid words <span className="font-normal text-gray-500">(optional)</span></span>
              <textarea className="min-h-28 w-full rounded-md border px-3 py-2 text-sm outline-none focus:border-black" value={fieldProps.value.avoidWords} disabled={fieldProps.disabled} onChange={(event) => fieldProps.updateValue("avoidWords", event.target.value)} />
            </label>
          ) : null}
        </div>

        {validationError ? <p className="mt-4 text-sm text-red-600" role="alert">{validationError}</p> : null}
        {error ? <p className="mt-4 text-sm text-red-600" role="alert">{error}</p> : null}
        <div className="mt-8 flex flex-wrap justify-between gap-3">
          <button className="rounded-md border px-4 py-2 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50" type="button" disabled={step === 0 || isSaving} onClick={previousStep}>Previous</button>
          {step < STEPS.length - 1 ? (
            <button
              className="rounded-md bg-black px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
              type="button"
              disabled={isSaving}
              onClick={(event) => {
                event.preventDefault();
                nextStep();
              }}
            >
              Next
            </button>
          ) : (
            <button className="rounded-md bg-black px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50" type="submit" disabled={isSaving}>{isSaving ? "Saving..." : "Complete kit"}</button>
          )}
        </div>
      </form>
    </section>
  );
}
