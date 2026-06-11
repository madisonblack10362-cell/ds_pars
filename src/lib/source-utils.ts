/**
 * Утилита для определения типа источника новости.
 *
 * Приоритет:
 *  1. sourceType из БД (если это известный тип)
 *  2. Авто-детекция по ссылкам (YouTube, Discord, Workshop и т.д.)
 *  3. Авто-детекция по тексту контента
 *  4. Фоллбэк — исходное значение
 */

const KNOWN_TYPES = new Set([
  'discord', 'telegram', 'vk', 'website', 'youtube',
  'workshop', 'patchnotes', 'reddit', 'manual',
])

/** Паттерны для детекции по ссылкам */
const LINK_PATTERNS: [RegExp, string][] = [
  [/youtu\.?be/i, 'youtube'],
  [/discord\.com/i, 'discord'],
  [/discord\.gg/i, 'discord'],
  [/steamcommunity\.com\/(?:workshop|sharedfiles)/i, 'workshop'],
  [/store\.steampowered\.com/i, 'workshop'],
  [/reddit\.com/i, 'reddit'],
  [/vk\.com/i, 'vk'],
  [/t\.me/i, 'telegram'],
]

/**
 * Определяет тип источника.
 *
 * @param dbType  — значение sourceType из БД (может быть пустым или "unknown")
 * @param links   — массив ссылок (уже распарсенный из JSON)
 * @param content — текстовое содержимое новости
 * @returns resolved source type string
 */
export function resolveSourceType(
  dbType: string,
  links: string[] = [],
  content: string = '',
): string {
  // 1. Если из БД пришел валидный тип — возвращаем его
  if (dbType && KNOWN_TYPES.has(dbType)) {
    return dbType
  }

  // 2. Пытаемся определить по ссылкам
  const allText = [...links, content].join(' ')

  for (const [pattern, type] of LINK_PATTERNS) {
    if (pattern.test(allText)) {
      return type
    }
  }

  // 3. Дополнительные проверки по содержимому
  if (content && /#\d{4,}/.test(content) && /discord/i.test(content)) {
    return 'discord'
  }

  if (/steam\s*workshop/i.test(content) || /steamcommunity\.com/i.test(content)) {
    return 'workshop'
  }

  // 4. Возвращаем исходное значение (или unknown если пустое)
  return dbType || 'unknown'
}