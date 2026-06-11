import { NextResponse } from 'next/server'
import { db } from '@/lib/db'

const ALLOWED_NEWS_TYPES = ['wipe', 'update', 'event', 'maintenance', 'patch', 'other']
const ALLOWED_PRIORITIES = ['low', 'medium', 'high']
const ALLOWED_STATUSES = ['pending', 'approved', 'published']

function isValidJsonArray(value: unknown): value is unknown[] {
  return Array.isArray(value)
}

// POST /api/news/create — manually create a news item (user auth, not bot webhook)
export async function POST(request: Request) {
  try {
    const body = await request.json()

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
      serverName,
      author,
    } = body

    // Validate required fields
    if (!content && !title) {
      return NextResponse.json({ error: 'Заголовок или содержание обязательно' }, { status: 400 })
    }

    // Validate types
    if (title && typeof title !== 'string') {
      return NextResponse.json({ error: 'Неверный формат заголовка' }, { status: 400 })
    }
    if (content && typeof content !== 'string') {
      return NextResponse.json({ error: 'Неверный формат содержания' }, { status: 400 })
    }

    // Validate enum fields
    if (newsType && !ALLOWED_NEWS_TYPES.includes(newsType)) {
      return NextResponse.json({ error: `Недопустимый тип новости: ${newsType}` }, { status: 400 })
    }
    if (priority && !ALLOWED_PRIORITIES.includes(priority)) {
      return NextResponse.json({ error: `Недопустимый приоритет: ${priority}` }, { status: 400 })
    }
    if (status && !ALLOWED_STATUSES.includes(status)) {
      return NextResponse.json({ error: `Недопустимый статус: ${status}` }, { status: 400 })
    }

    // Validate arrays
    if (images && !isValidJsonArray(images)) {
      return NextResponse.json({ error: 'images должен быть массивом' }, { status: 400 })
    }
    if (links && !isValidJsonArray(links)) {
      return NextResponse.json({ error: 'links должен быть массивом' }, { status: 400 })
    }

    // Find or create a "manual" source for user-created news
    let source = await db.source.findFirst({ where: { sourceType: 'manual' } })
    if (!source) {
      source = await db.source.create({
        data: {
          sourceType: 'manual',
          serverName: serverName || 'Ручная публикация',
          channelName: 'Web Panel',
          sourceId: 'manual',
          enabled: true,
        },
      })
    }

    const news = await db.newsItem.create({
      data: {
        sourceId: source.id,
        externalId: '',
        serverName: serverName || source.serverName,
        channelName: 'Web Panel',
        author: author || '',
        title: typeof title === 'string' ? title : '',
        content: typeof content === 'string' ? content : '',
        summary: typeof summary === 'string' ? summary : '',
        formattedPost: typeof formattedPost === 'string' ? formattedPost : '',
        newsType: ALLOWED_NEWS_TYPES.includes(newsType) ? newsType : 'other',
        priority: ALLOWED_PRIORITIES.includes(priority) ? priority : 'medium',
        status: ALLOWED_STATUSES.includes(status) ? status : 'pending',
        images: isValidJsonArray(images) ? JSON.stringify(images) : '[]',
        links: isValidJsonArray(links) ? JSON.stringify(links) : '[]',
      },
    })

    return NextResponse.json({ success: true, news_id: news.id }, { status: 201 })
  } catch (error) {
    console.error('Create news manual error:', error)
    return NextResponse.json({ error: 'Ошибка создания новости' }, { status: 500 })
  }
}
