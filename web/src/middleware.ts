import { NextResponse } from 'next/server';

const PROTECTED_API_PREFIXES = ['/api/sources', '/api/news', '/api/settings', '/api/stats', '/api/moderation'];

export function middleware(request: Request) {
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

  // For demo: just check the token exists and looks like a JWT (3 parts)
  // In production, verify the JWT signature
  try {
    const parts = token.split('.');
    if (parts.length !== 3) {
      throw new Error('Invalid token format');
    }

    // Decode the payload without verifying signature (demo only)
    const base64 = parts[1].replace(/-/g, '+').replace(/_/g, '/');
    // Use Buffer.from for Edge runtime compatibility
    const payloadStr = Buffer.from(base64, 'base64').toString('utf-8');
    const payload = JSON.parse(payloadStr);

    // Check expiration
    if (payload.exp && payload.exp < Math.floor(Date.now() / 1000)) {
      throw new Error('Token expired');
    }

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
