-- Existing databases may have applied 00017 before its authenticated grants
-- were added. Reapply the intended base privileges so RLS can enforce row
-- ownership for both application roles.
REVOKE ALL ON TABLE public.brand_kits FROM PUBLIC, anon;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.brand_kits TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.brand_kits TO service_role;
