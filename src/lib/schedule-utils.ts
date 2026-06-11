import { db, withDbRetry } from './db'

// Default schedule slots in MSK (UTC+3) — used only as initial defaults
export const DEFAULT_SLOTS: Record<string, string> = {
  schedule_slot_1_time: '07:00',
  schedule_slot_2_time: '13:00',
  schedule_slot_3_time: '18:00',
  schedule_slot_4_time: '21:00',
}

/** Get current time as if in MSK timezone (UTC+3) */
export function getMSKNow(): Date {
  const now = new Date()
  const utcMs = now.getTime() + now.getTimezoneOffset() * 60000
  return new Date(utcMs + 3 * 3600000)
}

/** Convert MSK time string "HH:MM" + MSK date → UTC Date */
export function mskTimeToUTC(mskTime: string, mskDate?: Date): Date {
  const [hours, minutes] = mskTime.split(':').map(Number)
  const date = mskDate || getMSKNow()
  const mskMs = Date.UTC(
    date.getUTCFullYear(),
    date.getUTCMonth(),
    date.getUTCDate(),
    hours,
    minutes,
    0,
    0
  )
  return new Date(mskMs - 3 * 3600000)
}

/**
 * Get all schedule slots from DB, falling back to DEFAULT_SLOTS for missing keys.
 * Returns a map: { schedule_slot_1_time: "07:00", schedule_slot_5_time: "23:00", ... }
 */
export async function getScheduleSlots(): Promise<Record<string, string>> {
  const settings = await withDbRetry(() =>
    db.settings.findMany({
      where: { key: { startsWith: 'schedule_slot_' } },
      orderBy: { key: 'asc' },
    })
  )
  const slots: Record<string, string> = {}
  // Start with defaults
  for (const [key, value] of Object.entries(DEFAULT_SLOTS)) {
    slots[key] = value
  }
  // Override / add from DB
  for (const s of settings) {
    slots[s.key] = s.value
  }
  return slots
}

/**
 * Find the next upcoming slot time based on current MSK time.
 * Returns a UTC Date for scheduling.
 */
export function mskTimeToNextSlot(slots: Record<string, string>): Date {
  const mskNow = getMSKNow()
  const mskHours = mskNow.getUTCHours()
  const mskMinutes = mskNow.getUTCMinutes()
  const nowMinutes = mskHours * 60 + mskMinutes

  // Collect all slot times in minutes, sorted
  const slotTimes: number[] = []
  for (const time of Object.values(slots)) {
    const [h, m] = time.split(':').map(Number)
    slotTimes.push(h * 60 + m)
  }
  slotTimes.sort((a, b) => a - b)

  // Find next upcoming slot today
  for (const slotMinutes of slotTimes) {
    if (slotMinutes > nowMinutes) {
      const [h, m] = [Math.floor(slotMinutes / 60), slotMinutes % 60]
      const utcMs = Date.UTC(
        mskNow.getUTCFullYear(),
        mskNow.getUTCMonth(),
        mskNow.getUTCDate(),
        h - 3,
        m,
        0,
        0
      )
      return new Date(utcMs)
    }
  }

  // No more slots today, use first slot tomorrow
  const [h, m] = [Math.floor(slotTimes[0] / 60), slotTimes[0] % 60]
  const tomorrowMSK = new Date(mskNow)
  tomorrowMSK.setUTCDate(tomorrowMSK.getUTCDate() + 1)
  const utcMs = Date.UTC(
    tomorrowMSK.getUTCFullYear(),
    tomorrowMSK.getUTCMonth(),
    tomorrowMSK.getUTCDate(),
    h - 3,
    m,
    0,
    0
  )
  return new Date(utcMs)
}

/**
 * Extract slot number from key. "schedule_slot_5_time" → 5
 */
export function slotKeyToNumber(key: string): number {
  const match = key.match(/schedule_slot_(\d+)_time/)
  return match ? parseInt(match[1], 10) : 0
}

/**
 * Get the next available slot key (e.g. schedule_slot_5_time if 1-4 exist)
 */
export function getNextSlotKey(existingKeys: string[]): string {
  const usedNumbers = existingKeys
    .map((k) => slotKeyToNumber(k))
    .filter((n) => n > 0)
  const maxNum = usedNumbers.length > 0 ? Math.max(...usedNumbers) : 0
  return `schedule_slot_${maxNum + 1}_time`
}

/** Validate HH:MM format */
export function isValidTime(time: string): boolean {
  return /^([01]?[0-9]|2[0-3]):[0-5][0-9]$/.test(time)
}
