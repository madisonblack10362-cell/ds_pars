import { PrismaClient } from '@prisma/client'

/**
 * Vercel serverless functions spin up/down rapidly.
 * We force transaction-mode PgBouncer (port 6543) so the web panel
 * doesn't exhaust the shared Supabase session-mode pool (15 max).
 */
function buildDatasourceUrl(): string {
  const url = process.env.DATABASE_URL!
  if (!url) return url

  let patched = url

  // Replace session-mode port 5432 with transaction-mode port 6543
  // when connecting through the Supabase pooler hostname
  patched = patched.replace(
    /(:\/\/[^/]+\.pooler\.supabase\.com):5432\//,
    '$1:6543/'
  )

  // Add pgbouncer flag so Prisma uses PgBouncer-compatible queries
  if (!patched.includes('pgbouncer=')) {
    const sep = patched.includes('?') ? '&' : '?'
    patched = `${patched}${sep}pgbouncer=true&connect_timeout=10`
  }

  return patched
}

const globalForPrisma = globalThis as unknown as {
  prisma: PrismaClient | undefined
}

export const db =
  globalForPrisma.prisma ??
  new PrismaClient({
    datasourceUrl: buildDatasourceUrl(),
  })

if (process.env.NODE_ENV !== 'production') globalForPrisma.prisma = db

/**
 * Retry helper — if a DB query fails because the pool is exhausted,
 * wait a short time and retry up to `retries` times.
 */
export async function withDbRetry<T>(fn: () => Promise<T>, retries = 2): Promise<T> {
  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      return await fn()
    } catch (error: unknown) {
      const msg = String(error)
      const isPoolError =
        msg.includes('max clients') ||
        msg.includes('EMAXCONNSESSION') ||
        msg.includes('connection') ||
        msg.includes('pool')
      if (isPoolError && attempt < retries) {
        await new Promise((r) => setTimeout(r, 500 * (attempt + 1)))
        continue
      }
      throw error
    }
  }
  throw new Error('withDbRetry: unreachable')
}