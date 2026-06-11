import { NextRequest, NextResponse } from 'next/server';
import { db } from '@/lib/db';

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;
    const news = await db.newsItem.findUnique({
      where: { id },
      include: {
        source: true,
      },
    });

    if (!news) {
      return NextResponse.json({ error: 'News not found' }, { status: 404 });
    }

    return NextResponse.json({ news });
  } catch (error) {
    console.error('Get news error:', error);
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
    const {
      title,
      content,
      summary,
      formattedPost,
      newsType,
      priority,
      status,
      images,
      links,
    } = body;

    const news = await db.newsItem.update({
      where: { id },
      data: {
        ...(title !== undefined && { title }),
        ...(content !== undefined && { content }),
        ...(summary !== undefined && { summary }),
        ...(formattedPost !== undefined && { formattedPost }),
        ...(newsType !== undefined && { newsType }),
        ...(priority !== undefined && { priority }),
        ...(status !== undefined && { status }),
        ...(images !== undefined && { images: JSON.stringify(images) }),
        ...(links !== undefined && { links: JSON.stringify(links) }),
      },
    });

    return NextResponse.json({ news });
  } catch (error) {
    console.error('Update news error:', error);
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    );
  }
}
