# Data Model: Brand Kit Interview

## `brand_kits`

One row belongs to exactly one `brands` row. `brand_id` is both the primary key and the foreign key, with `ON DELETE CASCADE`.

| Field | Type | Rules |
|---|---|---|
| `brand_id` | UUID | Required; primary key; owned through the parent brand |
| `tagline` | text | Optional; maximum 160 characters |
| `tone` | `tone_t` | Optional while partial; required for `complete`; values: `formal`, `casual`, `playful`, `professional`, `friendly` |
| `audience` | text | Optional while partial; when supplied, 2–500 non-whitespace characters; required for `complete` |
| `colors` | text[] | Default empty array for partial kits; 1–3 colors matching the canonical six-digit hexadecimal format `#RRGGBB` (leading `#` required; hex digits are case-insensitive) required for `complete` |
| `avoid_words` | text | Optional |
| `summary` | text | Null or partial while incomplete; deterministic derived text when complete |
| `status` | `kit_status_t` | `not_started`, `in_progress`, or `complete`; derived from saved answers |
| `completed_at` | timestamptz | Set when complete; cleared when an edit makes the kit incomplete |
| `created_at` | timestamptz | Database default |
| `updated_at` | timestamptz | Database default and existing updated-at trigger |

## Related `brands` response

Brand API responses gain a derived `kit_status` field. It is `not_started` when no `brand_kits` row exists, otherwise it mirrors the kit row’s status. No duplicated status column is added to `brands`.

## Validation and lifecycle

1. No row / no answers → `not_started`.
2. A row with at least one saved answer but incomplete required fields → `in_progress`.
3. A row with a valid name and all required answers, including 1–3 colors → `complete`, summary populated, `completed_at` set.
4. Editing a complete kit so a required field becomes invalid → `in_progress`, summary cleared, `completed_at` cleared.

## Deterministic summary

Only a `complete` kit receives a summary; incomplete kits persist and expose `summary: null`. The server generates the exact same string for the persisted `summary` and API response using this field order and template, with a single line-feed (`\n`) between lines and no trailing newline:

```text
Brand: {brand_name}
Tagline: {tagline}
Tone: {tone}
Audience: {audience}
Colors: {colors}
Avoid words: {avoid_words}
```

Before substitution, trim leading and trailing whitespace from every text value, collapse internal whitespace runs to one space, render `tone` in its enum spelling, normalize each color to uppercase canonical `#RRGGBB` while preserving array order, and join colors with `, `. Empty or omitted optional `tagline` and `avoid_words` values render as `None specified`; required values must already be valid. No client-supplied summary is accepted.

Examples:

- Complete without optional values → `Brand: Acme\nTagline: None specified\nTone: professional\nAudience: Small business owners\nColors: #FF5733, #3498DB\nAvoid words: None specified`.
- Incomplete with one saved answer → `status: in_progress`, `summary: null`.
- Complete with avoid words `cheap, discount` → the final line is `Avoid words: cheap, discount`; every other line remains in the same order and format.

These rules make the persisted and API-visible summary deterministic for the same normalized answers.

The existing brand name is updated in the same transaction as the kit upsert. Each write locks the owned brand row; overlapping successful writes use last-successful-save-wins behavior.

## Security and deletion

- Enable and force RLS on `brand_kits`.
- Permit authenticated access only through an owner policy using the existing `private.is_brand_owner(brand_id)` helper.
- Grant backend service-role DML and include the table in startup privilege assertions.
- A deleted brand cascades to its kit; integration tests verify no kit row remains.
