import { NextResponse } from 'next/server'
import { db } from '@/lib/db'
import { mskTimeToNextSlot, getScheduleSlots } from '@/lib/schedule-utils'

/**
 * Find next free slot — skips slots that already have items scheduled.
 * Returns the UTC Date for the next available slot.
 */
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

  // Try up to 7 days ahead to find a free slot
  while (dayOffset < 7) {
    for (const slotMinutes of slotTimes) {
      const [h, m] = [Math.floor(slotMinutes / 60), slotMinutes % 60]

      // Compute the UTC timestamp for this slot on the current day offset
      const slotDate = new Date(now)
      slotDate.setUTCDate(slotDate.getUTCDate() + dayOffset)
      // MSK = UTC+3, so slot at HH:00 MSK = (HH-3):00 UTC
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

      // Skip slots in the past (only on today, dayOffset=0)
      if (dayOffset === 0 && slotUTC <= now) continue

      // Check if any item is already scheduled for this slot
      const slotStart = new Date(slotMs)
      const slotEnd = new Date(slotMs + 60000) // 1 minute window
      const existing = await db.newsItem.count({
        where: {
          status: 'scheduled',
          scheduledAt: { gte: slotStart, lt: slotEnd },
        },
      })

      if (existing === 0) {
        return slotUTC
      }
    }
    dayOffset++
  }

  // Fallback — if all slots are full for 7 days, just use next slot from mskTimeToNextSlot
  return mskTimeToNextSlot(slots)
}

export async function POST(request: Request) {
  try {
    const body = await request.json()
    const { news_id, news_ids, action } = body

    if (news_ids && Array.isArray(news_ids)) {
      // Bulk action
      if (action === 'approve') {
        // Assign each item to its own free slot
        for (const id of news_ids) {
          const scheduledAt = await findNextFreeSlot()
          await db.newsItem.update({
            where: { id },
            data: { status: 'scheduled', scheduledAt },
          })
        }
        return NextResponse.json({ success: true, action, count: news_ids.length })
      }

      const updateData =
        action === 'reject'
          ? { status: 'rejected' }
          : action === 'publish'
            ? { status: 'published', publishedAt: new Date() }
            : {}

      const result = await db.newsItem.updateMany({
        where: { id: { in: news_ids } },
        data: updateData,
      })

      return NextResponse.json({ success: true, action, count: result.count })
    }

    if (news_id) {
      let updateData: Record<string, unknown> = {}
      if (action === 'approve') {
        const scheduledAt = await findNextFreeSlot()
        updateData = { status: 'scheduled', scheduledAt }
      } else if (action === 'reject') {
        updateData = { status: 'rejected' }
      } else if (action === 'publish') {
        updateData = { status: 'published', publishedAt: new Date() }
      }

      await db.newsItem.update({
        where: { id: news_id },
        data: updateData,
      })

      return NextResponse.json({ success: true, action, news_id })
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
    const { news_id, formatted_post, title, newsType, priority, summary, images } = body

    if (!news_id) {
      return NextResponse.json({ error: 'Отсутствует news_id' }, { status: 400 })
    }

    const data: Record<string, unknown> = {}
    if (formatted_post !== undefined) data.formattedPost = formatted_post
    if (title !== undefined) data.title = title
    if (newsType !== undefined) data.newsType = newsType
    if (priority !== undefined) data.priority = priority
    if (summary !== undefined) data.summary = summary
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
    console.error('Edit moderation error:', error)
    return NextResponse.json({ error: 'Ошибка сервера' }, { status: 500 })
  }
}
