import { NextResponse } from 'next/server'
import { db } from '@/lib/db'

export async function POST(request: Request) {
  try {
    const body = await request.json()
    const { news_id, news_ids, action } = body

    if (news_ids && Array.isArray(news_ids)) {
      // Bulk action
      const updateData =
        action === 'approve'
          ? { status: 'approved', publishedAt: new Date() }
          : action === 'reject'
            ? { status: 'rejected' }
            : action === 'publish'
              ? { status: 'published', publishedAt: new Date() }
              : {}

      const result = await db.newsItem.updateMany({
        where: { id: { in: news_ids } },
        data: updateData,
      })

      return NextResponse.json({
        success: true,
        action,
        count: result.count,
      })
    }

    if (news_id) {
      const updateData =
        action === 'approve'
          ? { status: 'approved', publishedAt: new Date() }
          : action === 'reject'
            ? { status: 'rejected' }
            : action === 'publish'
              ? { status: 'published', publishedAt: new Date() }
              : {}

      await db.newsItem.update({
        where: { id: news_id },
        data: updateData,
      })

      return NextResponse.json({
        success: true,
        action,
        news_id,
      })
    }

    return NextResponse.json({ error: 'Отсутствует news_id' }, { status: 400 })
  } catch (error) {
    console.error('Moderation error:', error)
    return NextResponse.json({ error: 'Ошибка сервера' }, { status: 500 })
  }
}

export async function PUT(request: Request) {
  try {
    const body = await request.json()
    const { news_id, formatted_post, title, newsType, priority, summary } = body

    if (!news_id) {
      return NextResponse.json({ error: 'Отсутствует news_id' }, { status: 400 })
    }

    const data: Record<string, unknown> = {}
    if (formatted_post !== undefined) data.formattedPost = formatted_post
    if (title !== undefined) data.title = title
    if (newsType !== undefined) data.newsType = newsType
    if (priority !== undefined) data.priority = priority
    if (summary !== undefined) data.summary = summary

    await db.newsItem.update({
      where: { id: news_id },
      data,
    })

    return NextResponse.json({ success: true, news_id })
  } catch (error) {
    console.error('Edit moderation error:', error)
    return NextResponse.json({ error: 'Ошибка сервера' }, { status: 500 })
  }
}
