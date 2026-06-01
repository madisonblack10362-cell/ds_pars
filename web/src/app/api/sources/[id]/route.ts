import { NextRequest, NextResponse } from 'next/server';
import { db } from '@/lib/db';

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;
    const source = await db.source.findUnique({
      where: { id },
      include: {
        news: {
          orderBy: { createdAt: 'desc' },
          take: 10,
        },
        _count: {
          select: { news: true },
        },
      },
    });

    if (!source) {
      return NextResponse.json({ error: 'Source not found' }, { status: 404 });
    }

    return NextResponse.json({ source });
  } catch (error) {
    console.error('Get source error:', error);
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    );
  }
}

export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;
    const body = await request.json();
    const { sourceType, serverName, sourceId, channelName, enabled, extra } = body;

    const source = await db.source.update({
      where: { id },
      data: {
        ...(sourceType !== undefined && { sourceType }),
        ...(serverName !== undefined && { serverName }),
        ...(sourceId !== undefined && { sourceId }),
        ...(channelName !== undefined && { channelName }),
        ...(enabled !== undefined && { enabled }),
        ...(extra !== undefined && { extra: JSON.stringify(extra) }),
      },
    });

    return NextResponse.json({ source });
  } catch (error) {
    console.error('Update source error:', error);
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    );
  }
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;

    await db.source.delete({
      where: { id },
    });

    return NextResponse.json({ success: true });
  } catch (error) {
    console.error('Delete source error:', error);
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    );
  }
}
