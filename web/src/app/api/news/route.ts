import { NextResponse } from 'next/server'
import { db } from '@/lib/db'

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url)
    const limit = parseInt(searchParams.get('limit') || '20')
    const offset = parseInt(searchParams.get('offset') || '0')
    const status = searchParams.get('status')
    const search = searchParams.get('search')
    const sourceType = searchParams.get('source_type')
    const newsType = searchParams.get('news_type')
    const priority = searchParams.get('priority')

    const where: Record<string, unknown> = {}

    if (status && status !== 'all') {
      where.status = status
    }
    if (newsType && newsType !== 'all') {
      where.newsType = newsType
    }
    if (priority && priority !== 'all') {
      where.priority = priority
    }
    if (search) {
      where.OR = [
        { content: { contains: search } },
        { title: { contains: search } },
        { summary: { contains: search } },
      ]
    }
    if (sourceType && sourceType !== 'all') {
      where.source = { sourceType }
    }

    const [news, total] = await Promise.all([
      db.newsItem.findMany({
        where,
        include: {
          source: {
            select: {
              sourceType: true,
              serverName: true,
              channelName: true,
            },
          },
        },
        orderBy: { createdAt: 'desc' },
        skip: offset,
        take: limit,
      }),
      db.newsItem.count({ where }),
    ])

    const totalPages = Math.ceil(total / limit)

    const formattedNews = news.map((item) => ({
      id: item.id,
      source_name: item.source?.serverName || item.serverName || 'Неизвестно',
      source_type: item.source?.sourceType || '',
      news_type: item.newsType || 'other',
      priority: item.priority || 'low',
      status: item.status || 'pending',
      original_text: item.content || '',
      title: item.title || '',
      ai_summary: item.summary || '',
      formatted_post: item.formattedPost || '',
      created_at: item.createdAt.toISOString(),
      published_at: item.publishedAt?.toISOString() || null,
      images: item.images || '[]',
      links: item.links || '[]',
    }))

    return NextResponse.json({
      news: formattedNews,
      total,
      totalPages,
      limit,
      offset,
    })
  } catch (error) {
    console.error('Fetch news error:', error)
    return NextResponse.json({ error: 'Ошибка получения новостей' }, { status: 500 })
  }
}

// POST endpoint for bot webhook - receives news from the bot
export async function POST(request: Request) {
  try {
    const body = await request.json()

    // Verify bot API key if set
    const botApiKey = process.env.BOT_API_KEY
    if (botApiKey) {
      const authHeader = request.headers.get('authorization')
      const apiKey = authHeader?.replace('Bearer ', '')
      if (apiKey !== botApiKey) {
        return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
      }
    }

    const {
      sourceId,
      externalId,
      serverName,
      channelName,
      author,
      title,
      content,
      summary,
      formattedPost,
      newsType,
      priority,
      images,
      links,
    } = body

    if (!content) {
      return NextResponse.json({ error: 'Content is required' }, { status: 400 })
    }

    // Find or create source
    let source = null
    if (sourceId) {
      source = await db.source.findUnique({ where: { id: sourceId } })
    }

    const news = await db.newsItem.create({
      data: {
        sourceId: source?.id || '',
        externalId: externalId || '',
        serverName: serverName || '',
        channelName: channelName || '',
        author: author || '',
        title: title || '',
        content,
        summary: summary || '',
        formattedPost: formattedPost || '',
        newsType: newsType || 'other',
        priority: priority || 'low',
        status: 'pending',
        images: images ? JSON.stringify(images) : '[]',
        links: links ? JSON.stringify(links) : '[]',
      },
    })

    return NextResponse.json({ success: true, news_id: news.id }, { status: 201 })
  } catch (error) {
    console.error('Create news error:', error)
    return NextResponse.json({ error: 'Ошибка создания новости' }, { status: 500 })
  }
}
