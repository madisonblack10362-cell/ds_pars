import { NextRequest, NextResponse } from 'next/server';
import { db } from '@/lib/db';

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { action, ids } = body;

    if (!action || !Array.isArray(ids) || ids.length === 0) {
      return NextResponse.json(
        { error: 'action and ids array are required' },
        { status: 400 }
      );
    }

    if (!['publish', 'reject'].includes(action)) {
      return NextResponse.json(
        { error: 'action must be "publish" or "reject"' },
        { status: 400 }
      );
    }

    const updateData =
      action === 'publish'
        ? { status: 'approved', publishedAt: new Date() }
        : { status: 'rejected' };

    const result = await db.newsItem.updateMany({
      where: { id: { in: ids } },
      data: updateData,
    });

    return NextResponse.json({
      success: true,
      updated: result.count,
      action,
    });
  } catch (error) {
    console.error('Bulk news error:', error);
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    );
  }
}
