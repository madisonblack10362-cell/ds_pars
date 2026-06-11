/**
 * Вспомогательные функции для отображения времени по Москве (MSK, UTC+3).
 */

export const MSK_TZ = 'Europe/Moscow'

/**
 * Конвертирует Date в "виртуальный" Date с датой/временем по МСК.
 * Нужно для сравнения дат (сегодня/вчера) в таймзоне Москвы.
 */
export function toMSK(date: Date): Date {
  const str = date.toLocaleString('en-US', { timeZone: MSK_TZ })
  return new Date(str)
}

/**
 * Форматирует дату как "Сегодня в 14:30", "Вчера в 14:30", или "01.06 в 14:30" по МСК.
 */
export function formatTimestamp(dateStr: string): string {
  const date = new Date(dateStr)
  const nowMSK = toMSK(new Date())
  const dateMSK = toMSK(date)
  const isToday =
    dateMSK.getDate() === nowMSK.getDate() &&
    dateMSK.getMonth() === nowMSK.getMonth() &&
    dateMSK.getFullYear() === nowMSK.getFullYear()

  const time = date.toLocaleTimeString('ru-RU', {
    hour: '2-digit',
    minute: '2-digit',
    timeZone: MSK_TZ,
  })

  if (isToday) {
    return `Сегодня в ${time}`
  }

  const yesterdayMSK = new Date(nowMSK)
  yesterdayMSK.setDate(yesterdayMSK.getDate() - 1)
  const isYesterday =
    dateMSK.getDate() === yesterdayMSK.getDate() &&
    dateMSK.getMonth() === yesterdayMSK.getMonth() &&
    dateMSK.getFullYear() === nowMSK.getFullYear()

  if (isYesterday) {
    return `Вчера в ${time}`
  }

  return date.toLocaleDateString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: dateMSK.getFullYear() !== nowMSK.getFullYear() ? 'numeric' : undefined,
    timeZone: MSK_TZ,
  }) + ` в ${time}`
}

/**
 * Форматирует дату как "01.06.2026, 14:30:00" по МСК.
 */
export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    timeZone: MSK_TZ,
  })
}

/**
 * Форматирует дату как "01.06.2026, 14:30" по МСК.
 */
export function formatDateTimeShort(iso: string): string {
  return new Date(iso).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: MSK_TZ,
  })
}

/**
 * Возвращает текущее время по МСК как "14:30".
 */
export function currentTimeMSK(): string {
  return new Date().toLocaleTimeString('ru-RU', {
    hour: '2-digit',
    minute: '2-digit',
    timeZone: MSK_TZ,
  })
}
