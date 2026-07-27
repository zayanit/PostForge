CREATE EXTENSION IF NOT EXISTS supabase_vault CASCADE;

CREATE TYPE provider_t AS ENUM ('openai', 'gemini');
CREATE TYPE provider_key_lifecycle_t AS ENUM ('normal', 'cleanup_required');
CREATE TYPE brand_deletion_state_t AS ENUM ('active', 'cleanup_required');

CREATE SCHEMA IF NOT EXISTS private;
REVOKE ALL ON SCHEMA private FROM PUBLIC, anon, authenticated;
GRANT USAGE ON SCHEMA private TO authenticated, service_role;

CREATE FUNCTION private.is_brand_owner(p_brand_id UUID)
RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
  SELECT EXISTS (
    SELECT 1
    FROM public.brands
    WHERE id = p_brand_id
      AND owner_user_id = (SELECT auth.uid())
  );
$$;

REVOKE ALL ON FUNCTION private.is_brand_owner(UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION private.is_brand_owner(UUID) TO authenticated, service_role;

ALTER TABLE brands
  ADD COLUMN deletion_state brand_deletion_state_t NOT NULL DEFAULT 'active';

ALTER TABLE brands DROP CONSTRAINT brands_logo_path_check;
ALTER TABLE brands ADD CONSTRAINT brands_logo_path_check CHECK (
  logo_path IS NULL
  OR logo_path ~ '^brands/[0-9a-f-]+/logo\.[A-Za-z0-9]+$'
  OR logo_path ~ '^brands/[0-9a-f-]+/logos/[0-9a-f-]+\.[A-Za-z0-9]+$'
);

ALTER TABLE brands DROP CONSTRAINT brands_owner_user_id_fkey;
ALTER TABLE brands ADD CONSTRAINT brands_owner_user_id_fkey
  FOREIGN KEY (owner_user_id) REFERENCES auth.users(id) ON DELETE RESTRICT;

CREATE FUNCTION reject_brand_cleanup_reversal()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = ''
AS $$
BEGIN
  IF OLD.deletion_state = 'cleanup_required'
     AND NEW.deletion_state = 'active' THEN
    RAISE EXCEPTION 'brand cleanup state is irreversible'
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER trg_brands_cleanup_irreversible
  BEFORE UPDATE ON brands
  FOR EACH ROW
  EXECUTE FUNCTION reject_brand_cleanup_reversal();

CREATE TABLE provider_keys (
  id UUID PRIMARY KEY,
  brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE RESTRICT,
  provider provider_t NOT NULL,
  vault_secret_id UUID NOT NULL,
  label TEXT CHECK (label IS NULL OR char_length(label) <= 100),
  key_hint TEXT NOT NULL CHECK (key_hint ~ '^\*\*\*[A-Za-z0-9_-]{4}$'),
  lifecycle provider_key_lifecycle_t NOT NULL DEFAULT 'normal',
  is_active BOOLEAN NOT NULL DEFAULT false,
  is_valid BOOLEAN,
  last_validated_at TIMESTAMPTZ,
  last_validation_error TEXT,
  validation_token UUID,
  validation_lease_expires_at TIMESTAMPTZ,
  last_used_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT provider_keys_cleanup_inactive CHECK (
    lifecycle <> 'cleanup_required' OR NOT is_active
  ),
  CONSTRAINT provider_keys_invalid_inactive CHECK (
    is_valid IS DISTINCT FROM false OR NOT is_active
  ),
  CONSTRAINT provider_keys_safe_validation_error CHECK (
    last_validation_error IS NULL
    OR last_validation_error = 'INVALID_CREDENTIAL'
  ),
  CONSTRAINT provider_keys_validation_lease_pair CHECK (
    (validation_token IS NULL AND validation_lease_expires_at IS NULL)
    OR (validation_token IS NOT NULL AND validation_lease_expires_at IS NOT NULL)
  ),
  CONSTRAINT provider_keys_cleanup_without_validation CHECK (
    lifecycle = 'normal' OR validation_token IS NULL
  ),
  CONSTRAINT provider_keys_validation_result CHECK (
    (is_valid IS NULL AND last_validated_at IS NULL AND last_validation_error IS NULL)
    OR (is_valid IS TRUE AND last_validated_at IS NOT NULL AND last_validation_error IS NULL)
    OR (
      is_valid IS FALSE
      AND last_validated_at IS NOT NULL
      AND last_validation_error = 'INVALID_CREDENTIAL'
    )
  )
);

CREATE UNIQUE INDEX uq_provider_keys_vault_secret
  ON provider_keys(vault_secret_id);
CREATE UNIQUE INDEX uq_provider_keys_one_active
  ON provider_keys(brand_id, provider)
  WHERE is_active;
CREATE INDEX idx_provider_keys_brand_provider_created
  ON provider_keys(brand_id, provider, created_at DESC, id DESC);
CREATE INDEX idx_provider_keys_cleanup
  ON provider_keys(brand_id, lifecycle)
  WHERE lifecycle = 'cleanup_required';

CREATE TRIGGER trg_provider_keys_updated_at
  BEFORE UPDATE ON provider_keys
  FOR EACH ROW
  EXECUTE FUNCTION set_updated_at();

CREATE FUNCTION reject_provider_key_cleanup_reversal()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = ''
AS $$
BEGIN
  IF OLD.lifecycle = 'cleanup_required' AND NEW.lifecycle = 'normal' THEN
    RAISE EXCEPTION 'provider key cleanup state is irreversible'
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER trg_provider_keys_cleanup_irreversible
  BEFORE UPDATE ON provider_keys
  FOR EACH ROW
  EXECUTE FUNCTION reject_provider_key_cleanup_reversal();

CREATE TABLE provider_key_idempotency (
  id UUID PRIMARY KEY,
  brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
  request_id UUID NOT NULL,
  provider_key_id UUID REFERENCES provider_keys(id) ON DELETE SET NULL,
  state TEXT NOT NULL CHECK (state IN ('active', 'deleted')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_provider_key_idempotency_brand_request UNIQUE (brand_id, request_id)
);

CREATE TABLE brand_asset_operations (
  id UUID PRIMARY KEY,
  brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE RESTRICT,
  operation TEXT NOT NULL CHECK (operation IN ('upload', 'remove')),
  object_path TEXT,
  previous_path TEXT,
  state TEXT NOT NULL CHECK (state IN ('in_progress', 'cleanup_required')),
  remote_status TEXT NOT NULL CHECK (
    remote_status IN ('pending', 'succeeded', 'failed', 'unknown')
  ),
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_brand_asset_operations_brand UNIQUE (brand_id)
);

CREATE TRIGGER trg_brand_asset_operations_updated_at
  BEFORE UPDATE ON brand_asset_operations
  FOR EACH ROW
  EXECUTE FUNCTION set_updated_at();

ALTER TABLE provider_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE provider_keys FORCE ROW LEVEL SECURITY;
ALTER TABLE provider_key_idempotency ENABLE ROW LEVEL SECURITY;
ALTER TABLE provider_key_idempotency FORCE ROW LEVEL SECURITY;
ALTER TABLE brand_asset_operations ENABLE ROW LEVEL SECURITY;
ALTER TABLE brand_asset_operations FORCE ROW LEVEL SECURITY;

CREATE POLICY provider_keys_select ON provider_keys
  FOR SELECT USING (private.is_brand_owner(brand_id));
CREATE POLICY provider_keys_insert ON provider_keys
  FOR INSERT WITH CHECK (private.is_brand_owner(brand_id));
CREATE POLICY provider_keys_update ON provider_keys
  FOR UPDATE
  USING (private.is_brand_owner(brand_id))
  WITH CHECK (private.is_brand_owner(brand_id));
CREATE POLICY provider_keys_delete ON provider_keys
  FOR DELETE USING (private.is_brand_owner(brand_id));

CREATE POLICY provider_key_idempotency_owner ON provider_key_idempotency
  FOR ALL
  USING (private.is_brand_owner(brand_id))
  WITH CHECK (private.is_brand_owner(brand_id));
CREATE POLICY brand_asset_operations_owner ON brand_asset_operations
  FOR ALL
  USING (private.is_brand_owner(brand_id))
  WITH CHECK (private.is_brand_owner(brand_id));

REVOKE ALL ON provider_keys FROM PUBLIC, anon, authenticated;
REVOKE ALL ON provider_key_idempotency FROM PUBLIC, anon, authenticated;
REVOKE ALL ON brand_asset_operations FROM PUBLIC, anon, authenticated;
REVOKE ALL ON brands FROM authenticated;

GRANT SELECT, INSERT, UPDATE, DELETE ON provider_keys TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON provider_key_idempotency TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON provider_key_idempotency TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON brand_asset_operations TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON brand_asset_operations TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON brands TO service_role;

GRANT SELECT (
  id, provider, label, key_hint, lifecycle, is_active, is_valid,
  last_validated_at, last_validation_error, created_at
) ON provider_keys TO authenticated;
GRANT SELECT (
  id, name, logo_path, deletion_state, created_at, updated_at
) ON brands TO authenticated;

REVOKE ALL ON SCHEMA vault FROM PUBLIC, anon, authenticated;
REVOKE ALL ON ALL TABLES IN SCHEMA vault FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION vault.create_secret(TEXT, TEXT, TEXT, UUID)
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION vault.update_secret(UUID, TEXT, TEXT, TEXT, UUID)
  FROM PUBLIC, anon, authenticated;

REVOKE ALL ON SCHEMA vault FROM service_role;
REVOKE ALL ON ALL TABLES IN SCHEMA vault FROM service_role;
REVOKE ALL ON FUNCTION vault.create_secret(TEXT, TEXT, TEXT, UUID)
  FROM service_role;
REVOKE ALL ON FUNCTION vault.update_secret(UUID, TEXT, TEXT, TEXT, UUID)
  FROM service_role;

GRANT USAGE ON SCHEMA vault TO service_role;
GRANT EXECUTE ON FUNCTION vault.create_secret(TEXT, TEXT, TEXT, UUID)
  TO service_role;
GRANT SELECT (id, decrypted_secret) ON vault.decrypted_secrets TO service_role;
GRANT SELECT (id) ON vault.secrets TO service_role;
GRANT DELETE ON vault.secrets TO service_role;
