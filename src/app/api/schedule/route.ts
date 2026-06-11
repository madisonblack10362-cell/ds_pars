import { NextRequest, NextResponse } from 'next/server'
import { db, withDbRetry } from '@/lib/db'
import {
  getMSKNow,
  mskTimeToUTC,
  getScheduleSlots,
  getNextSlotKey,
  slotKeyToNumber,
  isValidTime,
} from '@/lib/schedule-utils'

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = request.nextUrl
    const dateParam = searchParams.get('date')

    const slots = await getScheduleSlots()

    // Get sorted slot keys by slot number
    const sortedKeys = Object.keys(slots).sort((a, b) => slotKeyToNumber(a) - slotKeyToNumber(b))

    // Determine the target MSK date to display
    const nowMSK = getMSKNow()
    let targetMSKDate: Date
    let isToday = true

    if (dateParam === 'today') {
      targetMSKDate = nowMSK
      isToday = true
    } else if (dateParam) {
      // Parse YYYY-MM-DD → construct a "fake MSK date" like getMSKNow() does:
      // getMSKNow returns a Date where .getUTC*() returns MSK values.
      // So we create UTC midnight + 3 hours to get a fake-MSK midnight date.
      const [yearStr, monthStr, dayStr] = dateParam.split('-').map(Number)
      // Create MSK midnight as a "fake MSK Date" (UTC components = MSK values)
      targetMSKDate = new Date(Date.UTC(yearStr!, monthStr! - 1, dayStr!, 0, 0, 0))
      // getMSKNow() = UTC + timezoneOffset + 3h. The resulting Date has UTC = MSK.
      // So to build a consistent "fake MSK Date" for a specific calendar day,
      // we just need Date.UTC(y, m-1, d) — this gives UTC midnight which
      // corresponds to MSK 03:00. But mskTimeToUTC(slotTime, thisDate) does:
      //   Date.UTC(thisDate.year, thisDate.month, thisDate.day, slotHours, slotMinutes) - 3h
      // So the slot's UTC will be (y, m-1, d, slotH-3, slotM) in real UTC.
      // The item's scheduledAt was set by mskTimeToNextSlot which also uses
      // Date.UTC(mskNow.year, mskNow.month, mskNow.day, slotH-3, slotM).
      // Both use the same formula, so matching works as long as the DATE part
      // (day of month in UTC) is the same. For MSK 07:00 → UTC 04:00 same day.
      // For MSK 00:00 → UTC 21:00 previous day — but our slots are 07:00+ so
      // UTC will always be 04:00+ which is the same UTC date. Safe.
      
      // Check if the requested date matches today in MSK
      isToday = (
        targetMSKDate.getUTCFullYear() === nowMSK.getUTCFullYear() &&
        targetMSKDate.getUTCMonth() === nowMSK.getUTCMonth() &&
        targetMSKDate.getUTCDate() === nowMSK.getUTCDate()
      )
    } else {
      targetMSKDate = nowMSK
      isToday = true
    }

    // Fetch news items scheduled for each slot
    const scheduledItems = await withDbRetry(() =>
      db.newsItem.findMany({
        where: { status: 'scheduled' },
        orderBy: { scheduledAt: 'asc' },
      })
    )

    // Organize scheduled items by slot for the TARGET date (not always today)
    const slotQueues: Record<string, typeof scheduledItems> = {}
    for (const key of sortedKeys) {
      slotQueues[key] = []
    }

    for (const item of scheduledItems) {
      if (item.scheduledAt) {
        for (const slotKey of sortedKeys) {
          const slotUTCTime = mskTimeToUTC(slots[slotKey], targetMSKDate)
          const itemUTC = item.scheduledAt
          if (
            itemUTC.getUTCHours() === slotUTCTime.getUTCHours() &&
            itemUTC.getUTCMinutes() === slotUTCTime.getUTCMinutes() &&
            itemUTC.getUTCDate() === slotUTCTime.getUTCDate() &&
            itemUTC.getUTCMonth() === slotUTCTime.getUTCMonth() &&
            itemUTC.getUTCFullYear() === slotUTCTime.getUTCFullYear()
          ) {
            slotQueues[slotKey].push(item)
          }
        }
      }
    }

    // Determine status for each slot
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const slotInfos: any[] = []
    let totalItems = 0
    for (const slotKey of sortedKeys) {
      const slotTime = slots[slotKey]
      const slotNum = slotKeyToNumber(slotKey)
      const [hours, minutes] = slotTime.split(':').map(Number)
      const queue = slotQueues[slotKey]
      totalItems += queue.length

      let status: 'waiting' | 'published' | 'empty' | 'skipped'
      if (isToday) {
        // For today: determine status based on current MSK time vs slot time
        if (nowMSK.getUTCHours() > hours || (nowMSK.getUTCHours() === hours && nowMSK.getUTCMinutes() >= minutes)) {
          status = queue.length > 0 ? 'published' : 'skipped'
        } else {
          status = queue.length > 0 ? 'waiting' : 'empty'
        }
      } else {
        // For future/past dates: just show queue status
        status = queue.length > 0 ? 'waiting' : 'empty'
      }

      slotInfos.push({
        slot: slotNum,
        key: slotKey,
        time: slotTime,
        utcTime: `${String(hours - 3 >= 0 ? hours - 3 : hours + 21).padStart(2, '0')}:${minutes.toString().padStart(2, '0')}`,
        queueCount: queue.length,
        status,
        queue: queue.map((item) => ({
          id: item.id,
          title: item.title,
          priority: item.priority,
          newsType: item.newsType,
          formattedPost: item.formattedPost || '',
          content: item.content || '',
          images: item.images || '[]',
          serverName: item.serverName || '',
          scheduledAt: item.scheduledAt?.toISOString(),
        })),
      })
    }

    // Format the date string for the response
    const dateStr = dateParam || `${targetMSKDate.getUTCFullYear()}-${String(targetMSKDate.getUTCMonth() + 1).padStart(2, '0')}-${String(targetMSKDate.getUTCDate()).padStart(2, '0')}`

    return NextResponse.json({
      date: dateStr,
      isToday,
      slots: slotInfos,
      totalItems,
    })
  } catch (error) {
    console.error('Fetch schedule error:', error)
    return NextResponse.json({ error: 'Ошибка получения расписания' }, { status: 500 })
  }
}

export async function PUT(request: Request) {
  try {
    const body = await request.json()
    const updates: Record<string, string> = {}

    for (const [key, value] of Object.entries(body)) {
      if (!key.startsWith('schedule_slot_') || !key.endsWith('_time')) continue
      if (value && !isValidTime(value as string)) {
        return NextResponse.json(
          { error: `Неверный формат времени для ${key}. Используйте ЧЧ:ММ` },
          { status: 400 }
        )
      }
      if (value) {
        updates[key] = value as string
      }
    }

    // Upsert each slot setting
    for (const [key, value] of Object.entries(updates)) {
      await db.settings.upsert({
        where: { key },
        update: { value },
        create: { key, value },
      })
    }

    return NextResponse.json({ success: true, slots: updates })
  } catch (error) {
    console.error('Update schedule error:', error)
    return NextResponse.json({ error: 'Ошибка обновления расписания' }, { status: 500 })
  }
}

/** POST — add a new slot */
export async function POST(request: Request) {
  try {
    const body = await request.json()
    const { time } = body

    if (!time || !isValidTime(time)) {
      return NextResponse.json(
        { error: 'Неверный формат времени. Используйте ЧЧ:ММ' },
        { status: 400 }
      )
    }

    // Check max 20 slots
    const existingSlots = await getScheduleSlots()
    if (Object.keys(existingSlots).length >= 20) {
      return NextResponse.json(
        { error: 'Максимум 20 слотов расписания' },
        { status: 400 }
      )
    }

    const newKey = getNextSlotKey(Object.keys(existingSlots))

    await db.settings.upsert({
      where: { key: newKey },
      update: { value: time },
      create: { key: newKey, value: time },
    })

    return NextResponse.json({ success: true, key: newKey, time })
  } catch (error) {
    console.error('Add schedule slot error:', error)
    return NextResponse.json({ error: 'Ошибка добавления слота' }, { status: 500 })
  }
}

/** DELETE — remove a slot and unschedule its items */
export async function DELETE(request: Request) {
  try {
    const body = await request.json()
    const { key } = body

    if (!key || !key.startsWith('schedule_slot_') || !key.endsWith('_time')) {
      return NextResponse.json({ error: 'Неверный ключ слота' }, { status: 400 })
    }

    // Check slot exists
    const setting = await db.settings.findUnique({ where: { key } })
    if (!setting) {
      return NextResponse.json({ error: 'Слот не найден' }, { status: 404 })
    }

    // Prevent deleting if only 1 slot left
    const allSlots = await getScheduleSlots()
    if (Object.keys(allSlots).length <= 1) {
      return NextResponse.json(
        { error: 'Нельзя удалить последний слот' },
        { status: 400 }
      )
    }

    // Get the slot time to unschedule items
    const slotTime = setting.value
    const mskDate = getMSKNow()
    const slotUTC = mskTimeToUTC(slotTime, mskDate)

    // Unschedule items assigned to this slot today
    const scheduledItems = await db.newsItem.findMany({
      where: {
        status: 'scheduled',
        scheduledAt: {
          gte: new Date(slotUTC.getTime() - 12 * 3600000), // 12h window
          lte: new Date(slotUTC.getTime() + 12 * 3600000),
        },
      },
    })

    if (scheduledItems.length > 0) {
      // Reschedule to next available slot (excluding the one being deleted)
      const remainingSlots = { ...allSlots }
      delete remainingSlots[key]
      const { mskTimeToNextSlot } = await import('@/lib/schedule-utils')
      const nextSlot = mskTimeToNextSlot(remainingSlots)

      await db.newsItem.updateMany({
        where: { id: { in: scheduledItems.map((i) => i.id) } },
        data: { scheduledAt: nextSlot },
      })
    }

    // Delete the slot setting
    await db.settings.delete({ where: { key } })

    return NextResponse.json({
      success: true,
      rescheduled: scheduledItems.length,
    })
  } catch (error) {
    console.error('Delete schedule slot error:', error)
    return NextResponse.json({ error: 'Ошибка удаления слота' }, { status: 500 })
  }
}
