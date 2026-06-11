import { NextResponse } from 'next/server';
import { jwtVerify } from 'jose';
import { getJwtSecretBytes } from '@/lib/auth';

const PROTECTED_API_PREFIXES = ['/api/sources', '/api/news', '/api/settings', '/api/stats', '/api/moderation'];

export async function middleware(request: Request) {
  const { pathname } = new URL(request.url);

  // Allow public routes
  if (
    pathname === '/login' ||
    pathname.startsWith('/api/auth') ||
    pathname.startsWith('/api/telegram-auth') ||
    pathname.startsWith('/api/bot-webhook') ||
    pathname === '/' ||
    pathname.startsWith('/_next') ||
    pathname.startsWith('/favicon') ||
    pathname.startsWith('/static') ||
    pathname.startsWith('/public')
  ) {
    return NextResponse.next();
  }

  // Check protected API routes
  const isProtectedApi = PROTECTED_API_PREFIXES.some(prefix => pathname.startsWith(prefix));

  // Check protected page routes
  const isProtectedPage = pathname.startsWith('/dashboard');

  if (!isProtectedApi && !isProtectedPage) {
    return NextResponse.next();
  }

  // Get token from Authorization header or cookie
  let token: string | null = null;

  const authHeader = request.headers.get('authorization');
  if (authHeader && authHeader.startsWith('Bearer ')) {
    token = authHeader.substring(7);
  }

  if (!token) {
    const cookieHeader = request.headers.get('cookie');
    if (cookieHeader) {
      const match = cookieHeader.match(/(?:^|;\s*)token=([^;]*)/);
      token = match ? match[1] : null;
    }
  }

  if (!token) {
    if (isProtectedApi) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }
    return NextResponse.redirect(new URL('/login', request.url));
  }

  // Verify JWT signature using jose (Edge-compatible)
  try {
    const secret = getJwtSecretBytes();
    const { payload } = await jwtVerify(token, secret);

    // Add user info to headers for downstream handlers
    const requestHeaders = new Headers(request.headers);
    requestHeaders.set('x-user-id', String(payload.userId || payload.sub || ''));
    requestHeaders.set('x-user-role', String(payload.role || 'user'));
    requestHeaders.set('x-user-username', String(payload.username || ''));

    return NextResponse.next({
      request: { headers: requestHeaders },
    });
  } catch {
    if (isProtectedApi) {
      return NextResponse.json({ error: 'Invalid or expired token' }, { status: 401 });
    }
    return NextResponse.redirect(new URL('/login', request.url));
  }
}

export const config = {
  matcher: [
    '/dashboard/:path*',
    '/api/sources/:path*',
    '/api/news/:path*',
    '/api/settings/:path*',
    '/api/stats/:path*',
    '/api/moderation/:path*',
  ],
};
