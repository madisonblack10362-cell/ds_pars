import { NextResponse } from 'next/server'
import { db, withDbRetry } from '@/lib/db'

/**
 * Cleanup API — removes old news images and rejected news to prevent DB bloat.
 *
 * Triggered:
 *   - Manually from Settings page
 *   - Automatically when GET /api/stats is called (once per day max)
 *   - Optionally via external cron (cron-job.org → GET /api/cleanup)
 *
 * Cleanup rules:
 *   1. Delete rejected news older than 7 days (full record + images)
 *   2. Clear images from published news older than 30 days (keep text, remove base64 bloat)
 *   3. Clear images from pending news older than 14 days (stale pending items)
 */
export async function GET() {
  try {
    const now = new Date()
    const results = { deleted: 0, imagesCleared: 0 }

    // 1. Delete rejected news older than 7 days
    const sevenDaysAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000)
    const deletedRejected = await db.newsItem.deleteMany({
      where: {
        status: 'rejected',
        createdAt: { lt: sevenDaysAgo },
      },
    })
    results.deleted += deletedRejected.count

    // 2. Clear images from published news older than 30 days
    const thirtyDaysAgo = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000)
    const clearedPublished = await db.newsItem.updateMany({
      where: {
        status: 'published',
        createdAt: { lt: thirtyDaysAgo },
        images: { not: '[]' },
      },
      data: { images: '[]' },
    })
    results.imagesCleared += clearedPublished.count

    // 3. Clear images from stale pending news older than 14 days
    const fourteenDaysAgo = new Date(now.getTime() - 14 * 24 * 60 * 60 * 1000)
    const clearedPending = await db.newsItem.updateMany({
      where: {
        status: 'pending',
        createdAt: { lt: fourteenDaysAgo },
        images: { not: '[]' },
      },
      data: { images: '[]' },
    })
    results.imagesCleared += clearedPending.count

    console.log(`[cleanup] Deleted ${results.deleted} rejected news, cleared images from ${results.imagesCleared} old items`)

    return NextResponse.json({
      success: true,
      ...results,
      message: `Удалено ${results.deleted} отклонённых, очищено ${results.imagesCleared} старых картинок`,
    })
  } catch (error) {
    console.error('Cleanup error:', error)
    return NextResponse.json({ error: 'Ошибка очистки', details: String(error) }, { status: 500 })
  }
}
