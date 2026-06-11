import { Badge } from '@/components/ui/badge'

const SOURCE_CONFIG: Record<string, { label: string; className: string }> = {
  discord:    { label: 'Discord',       className: 'bg-indigo-500/15 text-indigo-400 border-indigo-500/30' },
  telegram:   { label: 'Telegram',      className: 'bg-sky-500/15 text-sky-400 border-sky-500/30' },
  vk:         { label: 'VK',            className: 'bg-blue-500/15 text-blue-400 border-blue-500/30' },
  website:    { label: 'Сайт',          className: 'bg-teal-500/15 text-teal-400 border-teal-500/30' },
  youtube:    { label: 'YouTube',       className: 'bg-red-500/15 text-red-400 border-red-500/30' },
  workshop:   { label: 'Workshop',      className: 'bg-orange-500/15 text-orange-400 border-orange-500/30' },
  patchnotes: { label: 'Патч-ноуты',   className: 'bg-cyan-500/15 text-cyan-400 border-cyan-500/30' },
  reddit:     { label: 'Reddit',       className: 'bg-amber-500/15 text-amber-500 border-amber-500/30' },
  manual:     { label: 'Вручную',      className: 'bg-gray-500/15 text-gray-400 border-gray-500/30' },
  unknown:    { label: 'Неизвестно',   className: 'bg-zinc-500/10 text-zinc-400 border-zinc-500/20' },
}

export function SourceTypeBadge({ type }: { type: string }) {
  const c = SOURCE_CONFIG[type] || { label: type || '—', className: 'bg-secondary text-muted-foreground border-border' }
  return <Badge variant="outline" className={c.className}>{c.label}</Badge>
}

/** Все зарегистрированные типы источников (для фильтров) */
export const SOURCE_TYPES = Object.entries(SOURCE_CONFIG)
  .filter(([v]) => v !== 'unknown')
  .map(([value, { label }]) => ({ value, label }))