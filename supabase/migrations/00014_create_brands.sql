CREATE TABLE brands (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  name TEXT NOT NULL CHECK (
    char_length(btrim(name)) BETWEEN 2 AND 120
  ),
  logo_path TEXT CHECK (
    logo_path IS NULL
    OR logo_path ~ '^brands/[0-9a-f-]+/logo\.[A-Za-z0-9]+$'
  ),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX uq_brands_owner_name_ci
  ON brands(owner_user_id, lower(btrim(name)));

CREATE INDEX idx_brands_owner_created
  ON brands(owner_user_id, created_at DESC);

CREATE OR REPLACE FUNCTION brands_trim_name()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  NEW.name = btrim(NEW.name);
  RETURN NEW;
END;
$$;

CREATE TRIGGER trg_brands_trim_name
  BEFORE INSERT OR UPDATE ON brands
  FOR EACH ROW
  EXECUTE FUNCTION brands_trim_name();

CREATE TRIGGER trg_brands_updated_at
  BEFORE UPDATE ON brands
  FOR EACH ROW
  EXECUTE FUNCTION set_updated_at();

ALTER TABLE brands ENABLE ROW LEVEL SECURITY;
ALTER TABLE brands FORCE ROW LEVEL SECURITY;

CREATE POLICY brands_select ON brands
  FOR SELECT
  USING (owner_user_id = auth.uid());

CREATE POLICY brands_insert ON brands
  FOR INSERT
  WITH CHECK (owner_user_id = auth.uid());

CREATE POLICY brands_update ON brands
  FOR UPDATE
  USING (owner_user_id = auth.uid())
  WITH CHECK (owner_user_id = auth.uid());

CREATE POLICY brands_delete ON brands
  FOR DELETE
  USING (owner_user_id = auth.uid());

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE brands TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE brands TO service_role;
