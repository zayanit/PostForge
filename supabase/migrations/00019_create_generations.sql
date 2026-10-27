CREATE TABLE public.generations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id uuid NOT NULL REFERENCES public.brands(id) ON DELETE CASCADE,
    request_id uuid NOT NULL,
    request_hash text NOT NULL,
    prompt text NOT NULL CHECK (char_length(btrim(prompt)) BETWEEN 3 AND 4000),
    context_snapshot text NOT NULL,
    provider public.provider_t NOT NULL DEFAULT 'openai' CHECK (provider = 'openai'),
    model text NOT NULL DEFAULT 'gpt-image-2' CHECK (model = 'gpt-image-2'),
    provider_key_id uuid REFERENCES public.provider_keys(id) ON DELETE SET NULL,
    platform_preset text NOT NULL CHECK (platform_preset IN (
        'instagram_post', 'instagram_story', 'instagram_reel_cover',
        'facebook_post', 'facebook_cover', 'facebook_story', 'twitter_post',
        'twitter_header', 'linkedin_post', 'linkedin_banner', 'tiktok_video_cover',
        'youtube_thumbnail', 'youtube_banner')),
    width integer NOT NULL CHECK (width BETWEEN 256 AND 4096),
    height integer NOT NULL CHECK (height BETWEEN 256 AND 4096),
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','processing','succeeded','failed')),
    lease_token uuid,
    lease_expires_at timestamptz,
    upload_fence_until timestamptz,
    provider_request_id text,
    image_path text,
    error_code text,
    cleanup_required boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    UNIQUE (brand_id, request_id),
    CHECK (image_path IS NULL OR image_path = 'brands/' || brand_id::text || '/generations/' || id::text || '.png'),
    CHECK (
        (status = 'succeeded' AND image_path IS NOT NULL AND completed_at IS NOT NULL AND error_code IS NULL)
        OR (status = 'failed' AND image_path IS NULL AND completed_at IS NOT NULL AND error_code IS NOT NULL)
        OR (status IN ('pending','processing') AND image_path IS NULL AND completed_at IS NULL AND error_code IS NULL)
    ),
    CHECK ((status = 'processing' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)
        OR (status <> 'processing' AND lease_token IS NULL AND lease_expires_at IS NULL))
);

CREATE INDEX generations_history ON public.generations (brand_id, created_at DESC, id DESC);
CREATE INDEX generations_queue ON public.generations (created_at) WHERE status = 'pending';
CREATE INDEX generations_recovery ON public.generations (lease_expires_at) WHERE status = 'processing';
ALTER TABLE public.generations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.generations FORCE ROW LEVEL SECURITY;
CREATE POLICY generations_owner_read ON public.generations FOR SELECT TO authenticated
    USING (private.is_brand_owner(brand_id));
REVOKE ALL ON public.generations FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT ON public.generations TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.generations TO service_role;

INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES ('generation-assets', 'generation-assets', false, 52428800, ARRAY['image/png'])
ON CONFLICT (id) DO UPDATE SET public = false, file_size_limit = EXCLUDED.file_size_limit,
    allowed_mime_types = EXCLUDED.allowed_mime_types;
-- No client object policies. The backend signs URLs only after ownership checks.
