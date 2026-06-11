-- ============================================
-- DayZ News Monitor - Supabase Database Setup
-- Run this in Supabase SQL Editor:
-- https://supabase.com/dashboard -> your project -> SQL Editor -> New query
-- ============================================

-- Create tables
CREATE TABLE IF NOT EXISTS "User" (
    "id" TEXT NOT NULL,
    "username" TEXT NOT NULL,
    "password" TEXT NOT NULL,
    "role" TEXT NOT NULL DEFAULT 'admin',
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    CONSTRAINT "User_pkey" PRIMARY KEY ("id")
);

CREATE TABLE IF NOT EXISTS "Source" (
    "id" TEXT NOT NULL,
    "sourceType" TEXT NOT NULL DEFAULT '',
    "serverName" TEXT NOT NULL DEFAULT '',
    "sourceId" TEXT NOT NULL DEFAULT '',
    "channelName" TEXT NOT NULL DEFAULT '',
    "enabled" BOOLEAN NOT NULL DEFAULT true,
    "extra" TEXT NOT NULL DEFAULT '{}',
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    CONSTRAINT "Source_pkey" PRIMARY KEY ("id")
);

CREATE TABLE IF NOT EXISTS "NewsItem" (
    "id" TEXT NOT NULL,
    "sourceId" TEXT NOT NULL,
    "externalId" TEXT NOT NULL DEFAULT '',
    "serverName" TEXT NOT NULL DEFAULT '',
    "channelName" TEXT NOT NULL DEFAULT '',
    "author" TEXT NOT NULL DEFAULT '',
    "title" TEXT NOT NULL DEFAULT '',
    "content" TEXT NOT NULL DEFAULT '',
    "summary" TEXT NOT NULL DEFAULT '',
    "formattedPost" TEXT NOT NULL DEFAULT '',
    "newsType" TEXT NOT NULL DEFAULT '',
    "priority" TEXT NOT NULL DEFAULT 'low',
    "status" TEXT NOT NULL DEFAULT 'pending',
    "images" TEXT NOT NULL DEFAULT '[]',
    "links" TEXT NOT NULL DEFAULT '[]',
    "publishedAtSource" TEXT,
    "publishedAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    CONSTRAINT "NewsItem_pkey" PRIMARY KEY ("id")
);

CREATE TABLE IF NOT EXISTS "Settings" (
    "key" TEXT NOT NULL,
    "value" TEXT NOT NULL DEFAULT '',
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    CONSTRAINT "Settings_pkey" PRIMARY KEY ("key")
);

CREATE TABLE IF NOT EXISTS "Log" (
    "id" TEXT NOT NULL,
    "level" TEXT NOT NULL DEFAULT 'info',
    "module" TEXT NOT NULL DEFAULT '',
    "message" TEXT NOT NULL,
    "details" TEXT NOT NULL DEFAULT '',
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "Log_pkey" PRIMARY KEY ("id")
);

-- Indexes
CREATE UNIQUE INDEX IF NOT EXISTS "User_username_key" ON "User"("username");

-- Foreign Key
DO $$ BEGIN
    ALTER TABLE "NewsItem" ADD CONSTRAINT "NewsItem_sourceId_fkey"
        FOREIGN KEY ("sourceId") REFERENCES "Source"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- Admin user (login: admin, password: admin123)
INSERT INTO "User" ("id", "username", "password", "role", "createdAt", "updatedAt")
VALUES (
    gen_random_uuid()::text,
    'admin',
    '$2b$12$lw/nK0JTKUWlhUGHsmlFNuzmhorODY72NVvQwAyQn2tbpwv4zo1C.',
    'admin',
    NOW(),
    NOW()
) ON CONFLICT ("username") DO NOTHING;

-- Default settings
INSERT INTO "Settings" ("key", "value", "createdAt", "updatedAt") VALUES
    ('site_name', 'DayZ News Monitor', NOW(), NOW()),
    ('check_interval', '5', NOW(), NOW()),
    ('publish_high_priority', 'true', NOW(), NOW()),
    ('publish_medium_priority', 'true', NOW(), NOW()),
    ('publish_low_priority', 'false', NOW(), NOW()),
    ('similarity_threshold', '0.85', NOW(), NOW())
ON CONFLICT ("key") DO NOTHING;

-- Sample sources
INSERT INTO "Source" ("id", "sourceType", "serverName", "sourceId", "channelName", "enabled", "createdAt", "updatedAt") VALUES
    ('discord-official', 'discord', 'DayZ Official', '1193299841988694216', 'dayz-news', true, NOW(), NOW()),
    ('telegram-ru-community', 'telegram', 'DayZ RU Community', '-1002566479222', 'general', true, NOW(), NOW())
ON CONFLICT DO NOTHING;
