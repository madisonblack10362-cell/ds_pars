import { NextResponse } from 'next/server'
import { db, withDbRetry } from '@/lib/db'
import { processImageUrls } from '@/lib/image-storage'

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

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const where: any = {}

    if (status && status !== 'all') {
      where.status = status
    } else {
      // По умолчанию не показываем отклонённые новости
      where.status = { not: 'rejected' }
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

    const [news, total] = await withDbRetry(() =>
      Promise.all([
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
    )

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
    }, {
      headers: { 'Cache-Control': 'no-store' },
    })
  } catch (error) {
    console.error('Fetch news error:', error)
    return NextResponse.json({ error: 'Ошибка получения новостей', details: String((error as Error)?.message || error) }, { status: 500 })
  }
}

// POST endpoint for bot webhook - receives news from the bot
export async function POST(request: Request) {
  try {
    const body = await request.json()

    // API key auth — если BOT_API_KEY настроен, обязательно проверяем
    const botApiKey = process.env.BOT_API_KEY
    if (botApiKey) {
      const authHeader = request.headers.get('authorization')
      const apiKey = authHeader?.replace('Bearer ', '')
      if (!apiKey || apiKey !== botApiKey) {
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

    // Find or create source — бот может отправлять sourceId как тип ("discord")
    // или как UUID существующего источника. Создаём Source если его нет.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let source: any = null
    if (sourceId) {
      // Проверяем — это UUID или тип источника?
      const isUUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(sourceId)
      if (isUUID) {
        source = await db.source.findUnique({ where: { id: sourceId } })
      }
      if (!source) {
        // Ищем по sourceType
        source = await db.source.findFirst({ where: { sourceType: sourceId } })
      }
      if (!source) {
        // Создаём новый источник
        source = await db.source.create({
          data: {
            sourceType: sourceId,
            serverName: serverName || sourceId,
            channelName: channelName || '',
          },
        })
      }
    }

    // Если source не найден и не создан — создаём дефолтный
    if (!source) {
      source = await db.source.create({
        data: {
          sourceType: sourceId || 'unknown',
          serverName: serverName || 'Unknown',
          channelName: channelName || '',
        },
      })
    }

    if (!source) {
      return NextResponse.json({ error: 'Failed to create source' }, { status: 500 })
    }

    // Process images: download Discord CDN URLs → permanent base64 data URLs
    let processedImages: string[] = []
    if (images && Array.isArray(images) && images.length > 0) {
      processedImages = await processImageUrls(images)
    }

    const news = await db.newsItem.create({
      data: {
        sourceId: source.id,
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
        images: processedImages.length > 0 ? JSON.stringify(processedImages) : '[]',
        links: links ? JSON.stringify(links) : '[]',
      },
    })

    return NextResponse.json({ success: true, news_id: news.id }, { status: 201 })
  } catch (error) {
    console.error('Create news error:', error)
    return NextResponse.json({ error: 'Ошибка создания новости', details: String(error) }, { status: 500 })
  }
}

// DELETE endpoint — remove news item completely from database
export async function DELETE(request: Request) {
  try {
    const { searchParams } = new URL(request.url)
    const id = searchParams.get('id')

    if (!id) {
      return NextResponse.json({ error: 'id is required' }, { status: 400 })
    }

    await withDbRetry(() =>
      db.newsItem.delete({ where: { id } })
    )

    return NextResponse.json({ success: true })
  } catch (error) {
    console.error('Delete news error:', error)
    return NextResponse.json({ error: 'Ошибка удаления новости', details: String((error as Error)?.message || error) }, { status: 500 })
  }
}
