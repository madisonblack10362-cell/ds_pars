import { NextResponse } from 'next/server'
import { db } from '@/lib/db'

export async function GET() {
  try {
    const now = new Date()

    // Auto-cleanup once per day (check stored timestamp)
    try {
      const lastCleanup = await db.settings.findUnique({ where: { key: 'last_cleanup' } })
      const lastCleanupDate = lastCleanup?.value ? new Date(lastCleanup.value) : null
      const oneDayAgo = new Date(now.getTime() - 24 * 60 * 60 * 1000)

      if (!lastCleanupDate || lastCleanupDate < oneDayAgo) {
        // Trigger cleanup in background (don't block stats response)
        const cleanupUrl = `${process.env.VERCEL_URL ? `https://${process.env.VERCEL_URL}` : ''}/api/cleanup`
        fetch(cleanupUrl, { signal: AbortSignal.timeout(5000) }).catch(() => {})
        await db.settings.upsert({
          where: { key: 'last_cleanup' },
          update: { value: now.toISOString() },
          create: { key: 'last_cleanup', value: now.toISOString() },
        })
      }
    } catch {
      // Cleanup failure should not break stats
    }

    const totalNews = await db.newsItem.count()
    const published = await db.newsItem.count({ where: { status: 'published' } })
    const approved = await db.newsItem.count({ where: { status: 'approved' } })
    const pending = await db.newsItem.count({ where: { status: 'pending' } })
    const rejected = await db.newsItem.count({ where: { status: 'rejected' } })
    const sources = await db.source.count({ where: { enabled: true } })

    // News by day (last 7 days)
    const newsByDay: { date: string; count: number }[] = []
    for (let i = 6; i >= 0; i--) {
      const dayStart = new Date(now)
      dayStart.setDate(dayStart.getDate() - i)
      dayStart.setHours(0, 0, 0, 0)

      const dayEnd = new Date(dayStart)
      dayEnd.setHours(23, 59, 59, 999)

      const count = await db.newsItem.count({
        where: {
          createdAt: { gte: dayStart, lte: dayEnd },
        },
      })

      newsByDay.push({
        date: dayStart.toISOString().split('T')[0],
        count,
      })
    }

    // News by type
    const newsByTypeRaw = await db.newsItem.groupBy({
      by: ['newsType'],
      _count: { newsType: true },
      where: { newsType: { not: '' } },
    })
    const typeLabels: Record<string, string> = {
      wipe: 'Вайп',
      update: 'Обновление',
      patch: 'Патч',
      event: 'Событие',
      maintenance: 'Обслуживание',
      other: 'Другое',
    }
    const newsByType = newsByTypeRaw.map((item) => ({
      type: typeLabels[item.newsType] || item.newsType,
      count: item._count.newsType,
    }))

    // News by priority
    const newsByPriorityRaw = await db.newsItem.groupBy({
      by: ['priority'],
      _count: { priority: true },
    })
    const newsByPriority = newsByPriorityRaw.map((item) => ({
      priority: item.priority,
      count: item._count.priority,
    }))

    // Error count (rejected)
    const errors = rejected

    return NextResponse.json({
      total_news: totalNews,
      published: published + approved,
      pending,
      sources,
      errors,
      news_by_day: newsByDay,
      news_by_type: newsByType,
      news_by_priority: newsByPriority,
    })
  } catch (error) {
    console.error('Stats error:', error)
    return NextResponse.json({ error: 'Ошибка получения статистики' }, { status: 500 })
  }
}
