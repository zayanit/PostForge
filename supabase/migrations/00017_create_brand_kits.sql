DO $$
DECLARE
  actual_labels TEXT[];
  type_kind "char";
BEGIN
  SELECT
    types.typtype,
    array_agg(enum_values.enumlabel::TEXT ORDER BY enum_values.enumsortorder)
  INTO type_kind, actual_labels
  FROM pg_type AS types
  JOIN pg_namespace AS namespaces ON namespaces.oid = types.typnamespace
  LEFT JOIN pg_enum AS enum_values ON enum_values.enumtypid = types.oid
  WHERE namespaces.nspname = 'public'
    AND types.typname = 'tone_t'
  GROUP BY types.oid, types.typtype;

  IF NOT FOUND THEN
    CREATE TYPE public.tone_t AS ENUM (
      'formal', 'casual', 'playful', 'professional', 'friendly'
    );
  ELSIF type_kind <> 'e'
     OR actual_labels IS DISTINCT FROM ARRAY[
       'formal', 'casual', 'playful', 'professional', 'friendly'
     ]::TEXT[] THEN
    RAISE EXCEPTION 'public.tone_t exists with an incompatible definition';
  END IF;
END;
$$;

DO $$
DECLARE
  actual_labels TEXT[];
  type_kind "char";
BEGIN
  SELECT
    types.typtype,
    array_agg(enum_values.enumlabel::TEXT ORDER BY enum_values.enumsortorder)
  INTO type_kind, actual_labels
  FROM pg_type AS types
  JOIN pg_namespace AS namespaces ON namespaces.oid = types.typnamespace
  LEFT JOIN pg_enum AS enum_values ON enum_values.enumtypid = types.oid
  WHERE namespaces.nspname = 'public'
    AND types.typname = 'kit_status_t'
  GROUP BY types.oid, types.typtype;

  IF NOT FOUND THEN
    CREATE TYPE public.kit_status_t AS ENUM (
      'not_started', 'in_progress', 'complete'
    );
  ELSIF type_kind <> 'e'
     OR actual_labels IS DISTINCT FROM ARRAY[
       'not_started', 'in_progress', 'complete'
     ]::TEXT[] THEN
    RAISE EXCEPTION 'public.kit_status_t exists with an incompatible definition';
  END IF;
END;
$$;

CREATE TABLE brand_kits (
  brand_id UUID PRIMARY KEY REFERENCES brands(id) ON DELETE CASCADE,
  tagline TEXT CHECK (tagline IS NULL OR char_length(tagline) <= 160),
  tone public.tone_t,
  audience TEXT CHECK (
    audience IS NULL OR char_length(btrim(audience)) BETWEEN 2 AND 500
  ),
  colors TEXT[] NOT NULL DEFAULT '{}'::TEXT[],
  avoid_words TEXT,
  summary TEXT,
  status public.kit_status_t NOT NULL DEFAULT 'not_started',
  completed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT brand_kits_colors_valid CHECK (
    COALESCE(array_ndims(colors), 1) = 1
    AND cardinality(colors) <= 3
    AND array_position(colors, NULL) IS NULL
    AND (
      cardinality(colors) = 0
      OR array_to_string(colors, ',') ~
        '^#[0-9A-Fa-f]{6}(,#[0-9A-Fa-f]{6}){0,2}$'
    )
  ),
  CONSTRAINT brand_kits_completion_valid CHECK (
    (
      status = 'complete'
      AND tone IS NOT NULL
      AND audience IS NOT NULL
      AND cardinality(colors) BETWEEN 1 AND 3
      AND summary IS NOT NULL
      AND completed_at IS NOT NULL
    )
    OR (
      status <> 'complete'
      AND summary IS NULL
      AND completed_at IS NULL
    )
  )
);

CREATE TRIGGER trg_brand_kits_updated_at
  BEFORE UPDATE ON brand_kits
  FOR EACH ROW
  EXECUTE FUNCTION set_updated_at();

ALTER TABLE brand_kits ENABLE ROW LEVEL SECURITY;
ALTER TABLE brand_kits FORCE ROW LEVEL SECURITY;

CREATE POLICY brand_kits_owner ON brand_kits
  FOR ALL
  USING (private.is_brand_owner(brand_id))
  WITH CHECK (private.is_brand_owner(brand_id));

REVOKE ALL ON brand_kits FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON brand_kits TO service_role;
