import { NextResponse } from 'next/server'
import { db } from '@/lib/db'
import { getScheduleSlots, mskTimeToNextSlot } from '@/lib/schedule-utils'

async function findNextFreeSlot(): Promise<Date> {
  const slots = await getScheduleSlots()
  const slotTimes = Object.values(slots)
    .map((t) => {
      const [h, m] = t.split(':').map(Number)
      return h * 60 + m
    })
    .sort((a, b) => a - b)

  const now = new Date()
  let dayOffset = 0

  while (dayOffset < 7) {
    for (const slotMinutes of slotTimes) {
      const [h, m] = [Math.floor(slotMinutes / 60), slotMinutes % 60]
      const slotDate = new Date(now)
      slotDate.setUTCDate(slotDate.getUTCDate() + dayOffset)
      const slotMs = Date.UTC(
        slotDate.getUTCFullYear(),
        slotDate.getUTCMonth(),
        slotDate.getUTCDate(),
        h - 3,
        m,
        0,
        0
      )
      const slotUTC = new Date(slotMs)

      if (dayOffset === 0 && slotUTC <= now) continue

      const slotStart = new Date(slotMs)
      const slotEnd = new Date(slotMs + 60000)
      const existing = await db.newsItem.count({
        where: {
          status: 'scheduled',
          scheduledAt: { gte: slotStart, lt: slotEnd },
        },
      })

      if (existing === 0) return slotUTC
    }
    dayOffset++
  }
  return mskTimeToNextSlot(slots)
}

export async function GET() {
  try {
    const items = await db.newsItem.findMany({
      where: { status: 'scheduled' },
      orderBy: { scheduledAt: 'asc' },
      include: { source: { select: { serverName: true, channelName: true } } },
    })

    return NextResponse.json({
      items: items.map((item) => ({
        id: item.id,
        title: item.title,
        summary: item.summary,
        content: item.content,
        formattedPost: item.formattedPost,
        images: item.images,
        links: item.links,
        newsType: item.newsType,
        priority: item.priority,
        serverName: item.source?.serverName || item.serverName,
        channelName: item.source?.channelName || item.channelName,
        scheduledAt: item.scheduledAt,
        createdAt: item.createdAt,
      })),
    })
  } catch (error) {
    console.error('Fetch publish queue error:', error)
    return NextResponse.json({ error: 'Ошибка получения очереди' }, { status: 500 })
  }
}

export async function POST(request: Request) {
  try {
    const body = await request.json()
    const { news_id, news_ids } = body

    if (news_ids && Array.isArray(news_ids)) {
      // Assign each item to its own free slot
      for (const id of news_ids) {
        const scheduledAt = await findNextFreeSlot()
        await db.newsItem.update({
          where: { id },
          data: { status: 'scheduled', scheduledAt },
        })
      }
      return NextResponse.json({ success: true, count: news_ids.length })
    }

    if (news_id) {
      const scheduledAt = await findNextFreeSlot()
      await db.newsItem.update({
        where: { id: news_id },
        data: { status: 'scheduled', scheduledAt },
      })
      return NextResponse.json({ success: true, news_id, scheduledAt })
    }

    return NextResponse.json({ error: 'Отсутствует news_id' }, { status: 400 })
  } catch (error) {
    console.error('Schedule publish error:', error)
    return NextResponse.json({ error: 'Ошибка сервера' }, { status: 500 })
  }
}

export async function PUT(request: Request) {
  try {
    const body = await request.json()
    const { news_id, formatted_post, images } = body

    if (!news_id) {
      return NextResponse.json({ error: 'Отсутствует news_id' }, { status: 400 })
    }

    const data: Record<string, unknown> = {}
    if (formatted_post !== undefined) data.formattedPost = formatted_post
    if (images !== undefined) {
      if (typeof images === 'string') {
        data.images = images
      } else if (Array.isArray(images)) {
        data.images = JSON.stringify(images)
      }
    }

    await db.newsItem.update({
      where: { id: news_id },
      data,
    })

    return NextResponse.json({ success: true, news_id })
  } catch (error) {
    console.error('Edit scheduled item error:', error)
    return NextResponse.json({ error: 'Ошибка сервера' }, { status: 500 })
  }
}
