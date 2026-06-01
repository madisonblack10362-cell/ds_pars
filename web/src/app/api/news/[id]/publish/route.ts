import { NextRequest, NextResponse } from 'next/server';
import { db } from '@/lib/db';

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;

    const news = await db.newsItem.update({
      where: { id },
      data: {
        status: 'approved',
        publishedAt: new Date(),
      },
    });

    return NextResponse.json({ news });
  } catch (error) {
    console.error('Publish news error:', error);
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    );
  }
}
