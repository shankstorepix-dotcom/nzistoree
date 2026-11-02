-- ============================================================================
-- NziStore · Supabase PostgreSQL Schema + Row Level Security (RLS) + pgcrypto
-- Zero-Trust / Backend-Only Architecture
-- Sensitive columns (delivery_stock.content, order_items.delivery_text,
-- order_messages.text) are encrypted at the application layer with AES-256-GCM
-- (enc:gcm1:<nonce+tag+ciphertext>) before being stored in the database.
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- 1. Core Tables
CREATE TABLE IF NOT EXISTS public.users (
    id BIGSERIAL PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'customer')),
    email_verified INTEGER NOT NULL DEFAULT 1 CHECK (email_verified IN (0, 1))
);

CREATE TABLE IF NOT EXISTS public.user_profiles (
    user_id BIGINT PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
    nickname TEXT NOT NULL,
    changed_at BIGINT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS public.sessions (
    token TEXT PRIMARY KEY,
    user_id BIGINT UNIQUE REFERENCES public.users(id) ON DELETE CASCADE,
    csrf TEXT NOT NULL,
    expires BIGINT NOT NULL,
    refresh_token TEXT UNIQUE,
    absolute_expires BIGINT
);

CREATE TABLE IF NOT EXISTS public.used_refresh_tokens (
    token_hash TEXT PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    expires BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS public.email_otps (
    email TEXT PRIMARY KEY,
    code_hash TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    expires BIGINT NOT NULL,
    sent_at BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS public.oauth_states (
    state_hash TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    verifier TEXT NOT NULL,
    expires BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS public.oauth_accounts (
    provider TEXT NOT NULL,
    provider_user_id TEXT NOT NULL,
    user_id BIGINT NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    created BIGINT NOT NULL,
    PRIMARY KEY (provider, provider_user_id)
);

CREATE TABLE IF NOT EXISTS public.admin_credentials (
    user_id BIGINT PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
    pin_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS public.admin_sessions (
    token TEXT PRIMARY KEY REFERENCES public.sessions(token) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS public.store_categories (
    slug TEXT PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    image TEXT NOT NULL DEFAULT '',
    position INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS public.roblox_subcategories (
    id BIGSERIAL PRIMARY KEY,
    slug TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    image TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS public.products (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    price INTEGER NOT NULL,
    compare_price INTEGER NOT NULL DEFAULT 0,
    video_url TEXT NOT NULL DEFAULT '',
    min_quantity INTEGER NOT NULL DEFAULT 1,
    max_quantity INTEGER NOT NULL DEFAULT 99,
    has_variants INTEGER NOT NULL DEFAULT 0,
    category TEXT NOT NULL,
    image TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS public.product_variants (
    id BIGSERIAL PRIMARY KEY,
    product_id BIGINT NOT NULL REFERENCES public.products(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    price INTEGER NOT NULL,
    compare_price INTEGER NOT NULL DEFAULT 0,
    stock INTEGER NOT NULL DEFAULT 0,
    position INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS public.product_subcategories (
    product_id BIGINT PRIMARY KEY REFERENCES public.products(id) ON DELETE CASCADE,
    subcategory_id BIGINT NOT NULL REFERENCES public.roblox_subcategories(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS public.product_delivery (
    product_id BIGINT PRIMARY KEY REFERENCES public.products(id) ON DELETE CASCADE,
    mode TEXT NOT NULL DEFAULT 'manual' CHECK (mode IN ('manual', 'automatic')),
    robux_quantity INTEGER NOT NULL DEFAULT 0 CHECK (robux_quantity >= 0)
);

-- Encrypted with AES-256-GCM (enc:gcm1:...) at the application layer
CREATE TABLE IF NOT EXISTS public.delivery_stock (
    id BIGSERIAL PRIMARY KEY,
    product_id BIGINT NOT NULL REFERENCES public.products(id) ON DELETE RESTRICT,
    content TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    item_id BIGINT UNIQUE,
    created BIGINT NOT NULL,
    UNIQUE (product_id, fingerprint)
);

CREATE TABLE IF NOT EXISTS public.store_coupon (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    code TEXT NOT NULL,
    percent INTEGER NOT NULL CHECK (percent BETWEEN 1 AND 90),
    enabled INTEGER NOT NULL CHECK (enabled IN (0, 1))
);

CREATE TABLE IF NOT EXISTS public.orders (
    id TEXT PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES public.users(id),
    email TEXT NOT NULL,
    request_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    total INTEGER NOT NULL CHECK (total > 0),
    payment TEXT NOT NULL DEFAULT 'nao_iniciado'
        CHECK (payment IN ('nao_iniciado', 'criando', 'pendente', 'revisao', 'pago', 'falha', 'reembolsado')),
    provider_id TEXT,
    pix_code TEXT,
    roblox_id BIGINT,
    roblox_username TEXT,
    roblox_display_name TEXT,
    created BIGINT NOT NULL,
    paid_at BIGINT,
    UNIQUE (user_id, request_key)
);

-- delivery_text is encrypted with AES-256-GCM (enc:gcm1:...) at the application layer
CREATE TABLE IF NOT EXISTS public.order_items (
    id BIGSERIAL PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES public.orders(id) ON DELETE CASCADE,
    product_id BIGINT NOT NULL,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    unit_price INTEGER NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity BETWEEN 1 AND 99),
    mode TEXT NOT NULL CHECK (mode IN ('manual', 'automatic')),
    robux_quantity INTEGER NOT NULL DEFAULT 0,
    delivered_at BIGINT,
    delivery_text TEXT
);

CREATE TABLE IF NOT EXISTS public.order_coupons (
    order_id TEXT PRIMARY KEY REFERENCES public.orders(id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    discount INTEGER NOT NULL CHECK (discount >= 0)
);

CREATE TABLE IF NOT EXISTS public.order_tracking (
    order_id TEXT PRIMARY KEY REFERENCES public.orders(id) ON DELETE CASCADE,
    parameters TEXT NOT NULL,
    consent INTEGER NOT NULL CHECK (consent IN (0, 1)),
    payer_name TEXT
);

-- text is encrypted with AES-256-GCM (enc:gcm1:...) at the application layer
CREATE TABLE IF NOT EXISTS public.order_messages (
    id BIGSERIAL PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES public.orders(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES public.users(id),
    role TEXT NOT NULL CHECK (role IN ('customer', 'admin')),
    text TEXT NOT NULL,
    request_key TEXT NOT NULL,
    created BIGINT NOT NULL,
    UNIQUE (order_id, user_id, request_key)
);

CREATE TABLE IF NOT EXISTS public.chat_presence (
    order_id TEXT NOT NULL REFERENCES public.orders(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('customer', 'admin')),
    seen BIGINT NOT NULL,
    typing_until BIGINT NOT NULL DEFAULT 0,
    read_id BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (order_id, role)
);

CREATE TABLE IF NOT EXISTS public.commerce_jobs (
    id BIGSERIAL PRIMARY KEY,
    job_key TEXT UNIQUE NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('discord', 'payment', 'utmify')),
    order_id TEXT NOT NULL REFERENCES public.orders(id) ON DELETE CASCADE,
    payload TEXT NOT NULL DEFAULT '{}',
    attempts INTEGER NOT NULL DEFAULT 0,
    next_at BIGINT NOT NULL DEFAULT 0,
    lease TEXT,
    leased_until BIGINT NOT NULL DEFAULT 0,
    done INTEGER NOT NULL DEFAULT 0,
    last_error TEXT
);

CREATE TABLE IF NOT EXISTS public.daily_visits (
    day TEXT NOT NULL,
    visitor TEXT NOT NULL,
    state TEXT,
    country TEXT,
    PRIMARY KEY (day, visitor)
);

CREATE TABLE IF NOT EXISTS public.limits (
    bucket TEXT PRIMARY KEY,
    count INTEGER NOT NULL,
    expires BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS public.audit (
    id BIGSERIAL PRIMARY KEY,
    event TEXT NOT NULL,
    actor BIGINT,
    created BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS public.metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- ============================================================================
-- 2. Strict Row Level Security (RLS) — Deny-by-Default
-- ============================================================================
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC, anon, authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM PUBLIC, anon, authenticated;

DO $$
DECLARE
    tbl TEXT;
BEGIN
    FOREACH tbl IN ARRAY ARRAY[
        'users', 'user_profiles', 'sessions', 'used_refresh_tokens',
        'email_otps', 'oauth_states', 'oauth_accounts', 'admin_credentials',
        'admin_sessions', 'store_categories', 'roblox_subcategories',
        'products', 'product_variants', 'product_subcategories', 'product_delivery',
        'delivery_stock', 'store_coupon', 'orders', 'order_items',
        'order_coupons', 'order_tracking', 'order_messages',
        'chat_presence', 'commerce_jobs', 'daily_visits', 'limits',
        'audit', 'metadata'
    ]
    LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY;', tbl);
        EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY;', tbl);
    END LOOP;
END $$;
