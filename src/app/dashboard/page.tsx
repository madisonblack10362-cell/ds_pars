'use client'

import { sanitizeTelegramHtml } from '@/lib/sanitize'
import { useState, useEffect } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Newspaper,
  CheckCircle,
  Clock,
  AlertTriangle,
  Eye,
  MessageSquare,
} from 'lucide-react'
import Link from 'next/link'
import { formatTimestamp } from '@/lib/msk-time'

interface Stats {
  total_news: number
  published: number
  pending: number
  errors: number
  news_by_day: { date: string; count: number }[]
  news_by_type: { type: string; count: number }[]
  news_by_priority: { priority: string; count: number }[]
}

interface NewsItem {
  id: number
  source_name: string
  source_type: string
  news_type: string
  priority: string
  status: string
  original_text: string
  ai_summary: string
  formatted_post: string | null
  title: string
  created_at: string
  images: string
  links: string
}

function StatCard({
  title,
  value,
  icon: Icon,
  color,
  loading,
}: {
  title: string
  value: number
  icon: React.ElementType
  color: string
  loading: boolean
}) {
  return (
    <Card className="bg-card border-border">
      <CardContent className="p-4">
        <div className="flex items-center gap-4">
          <div
            className="w-10 h-10 rounded-lg flex items-center justify-center"
            style={{ backgroundColor: `${color}15` }}
          >
            <Icon className="w-5 h-5" style={{ color }} />
          </div>
          <div className="flex-1">
            <p className="text-xs text-muted-foreground">{title}</p>
            {loading ? (
              <Skeleton className="h-7 w-16 mt-1 bg-secondary" />
            ) : (
              <p className="text-2xl font-bold text-foreground">{value}</p>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function StatusBadge({ status }: { status: string }) {
  const config: Record<string, { label: string; className: string }> = {
    pending: { label: 'Ожидает', className: 'bg-yellow-500/15 text-yellow-400 border-yellow-500/30' },
    approved: { label: 'Одобрена', className: 'bg-green-500/15 text-green-400 border-green-500/30' },
    published: { label: 'Опубликована', className: 'bg-[#58a6ff]/15 text-[#58a6ff] border-[#58a6ff]/30' },
    rejected: { label: 'Отклонена', className: 'bg-red-500/15 text-red-400 border-red-500/30' },
    scheduled: { label: 'В расписании', className: 'bg-purple-500/15 text-purple-400 border-purple-500/30' },
  }
  const c = config[status] || { label: status, className: 'bg-secondary text-muted-foreground border-border' }
  return <Badge variant="outline" className={c.className}>{c.label}</Badge>
}

function PriorityBadge({ priority }: { priority: string }) {
  const config: Record<string, { label: string; className: string }> = {
    high: { label: 'Высокий', className: 'bg-red-500/15 text-red-400 border-red-500/30' },
    medium: { label: 'Средний', className: 'bg-yellow-500/15 text-yellow-400 border-yellow-500/30' },
    low: { label: 'Низкий', className: 'bg-gray-500/15 text-gray-400 border-gray-500/30' },
  }
  const c = config[priority] || { label: priority, className: 'bg-secondary text-muted-foreground border-border' }
  return <Badge variant="outline" className={c.className}>{c.label}</Badge>
}

function NewsTypeBadge({ type }: { type: string }) {
  const config: Record<string, { label: string; className: string }> = {
    wipe: { label: 'Вайп', className: 'bg-red-500/15 text-red-400 border-red-500/30' },
    update: { label: 'Обновление', className: 'bg-[#58a6ff]/15 text-[#58a6ff] border-[#58a6ff]/30' },
    patch: { label: 'Патч', className: 'bg-purple-500/15 text-purple-400 border-purple-500/30' },
    event: { label: 'Событие', className: 'bg-green-500/15 text-green-400 border-green-500/30' },
    maintenance: { label: 'Обслуживание', className: 'bg-yellow-500/15 text-yellow-400 border-yellow-500/30' },
    other: { label: 'Другое', className: 'bg-orange-500/15 text-orange-400 border-orange-500/30' },
  }
  const c = config[type] || { label: type, className: 'bg-secondary text-muted-foreground border-border' }
  return <Badge variant="outline" className={c.className}>{c.label}</Badge>
}

// ─── Telegram HTML → rich HTML for preview bubble ───
function telegramHtmlToRich(html: string): string {
  let text = html
    .replace(/([^>\n])\n(?![<])/g, '$1<br/>')
    .replace(/\n(?!<)/g, '<br/>')
    .replace(/<br\s*\/>/gi, '<br/>')
    .replace(/<br\s*>/gi, '<br/>')
    .replace(/<\/p>/gi, '<br/>')
    .replace(/<p[^>]*>/gi, '')
    .replace(/<\/div>/gi, '<br/>')
    .replace(/<div[^>]*>/gi, '')
    .replace(/<\/li>/gi, '<br/>')
    .replace(/<li[^>]*>/gi, '<span style="display:inline-block;margin-left:8px">•</span> ')
    .replace(/<ul[^>]*>|<ol[^>]*>/gi, '')
    .replace(/<\/ul>|<\/ol>/gi, '<br/>')
    .replace(/<blockquote>/gi, '<blockquote>')
    .replace(/<\/blockquote>/gi, '</blockquote><br/>')
    .replace(/(<br\s*\/>){3,}/g, '<br/><br/>')
  return sanitizeTelegramHtml(text)
}

// ─── Compact Telegram Preview ───
function TelegramPreview({
  text,
  images,
  time,
}: {
  text: string
  images: string[]
  time: string
}) {
  const richHtml = telegramHtmlToRich(text)
  const displayImage = images[0] || null

  return (
    <div className="rounded-xl overflow-hidden border border-[#2d3a54] w-full shadow-lg shadow-black/20" style={{minWidth:0}}>
      {/* TG top bar */}
      <div className="bg-[#2b5278] px-3 py-2 flex items-center gap-3">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" className="text-white/60 flex-shrink-0">
          <path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z" fill="currentColor"/>
        </svg>
        <div className="flex-1 min-w-0">
          <p className="text-[13px] font-semibold text-white truncate">DayZ Monitor</p>
          <p className="text-[11px] text-white/60">канал</p>
        </div>
      </div>

      {/* Message area */}
      <div className="bg-[#0e1621] px-3 pb-3 pt-1" style={{minWidth:0,overflowX:'hidden'}}>
        {/* Channel avatar + name */}
        <div className="flex items-center gap-2.5 mb-2">
          <div className="w-10 h-10 rounded-full bg-[#58a6ff]/20 flex items-center justify-center flex-shrink-0 border-2 border-[#58a6ff]/30">
            <MessageSquare className="w-5 h-5 text-[#58a6ff]" />
          </div>
          <div className="min-w-0">
            <p className="text-sm font-semibold text-[#58a6ff]">DayZ Monitor</p>
            <p className="text-[11px] text-[#6c7b8f]">канал</p>
          </div>
        </div>

        {/* Media preview */}
        {displayImage && (
          <div className="mb-1.5 overflow-hidden rounded-md bg-[#1a2733]" style={{maxHeight:300}}>
            <img
              src={displayImage}
              alt=""
              className="block w-full h-auto object-cover"
              style={{maxHeight:300,maxWidth:'100%'}}
              loading="lazy"
              referrerPolicy="no-referrer"
              onError={(e) => {
                (e.target as HTMLImageElement).style.display = 'none'
              }}
            />
          </div>
        )}

        {/* Message bubble */}
        <div className="bg-[#182533] rounded-xl rounded-tl-sm px-2.5 py-2 break-words" style={{maxWidth:'100%',overflowWrap:'break-word',wordBreak:'break-word'}}>
          <div
            className="text-sm text-[#f5f5f5] leading-[1.45] telegram-preview-content"
            style={{overflowWrap:'break-word',wordBreak:'break-word'}}
            dangerouslySetInnerHTML={{ __html: richHtml }}
          />
        </div>

        {/* Timestamp + check */}
        <div className="mt-1 flex items-center justify-end gap-1">
          <span className="text-[11px] text-[#6c7b8f]">{time}</span>
          <svg className="w-4 h-3 text-[#6c7b8f]" viewBox="0 0 16 11" fill="none">
            <path d="M11.071 0L4.5 6.571 1.429 3.5 0 4.929 4.5 9.429 12.5 1.429z" fill="currentColor"/>
          </svg>
        </div>
      </div>
    </div>
  )
}

function BarChart({ data, label }: { data: { date: string; count: number }[]; label: string }) {
  const maxCount = Math.max(...data.map((d) => d.count), 1)
  return (
    <Card className="bg-card border-border">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium">{label}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex items-end gap-2 h-40">
          {data.map((item, i) => (
            <div key={i} className="flex-1 flex flex-col items-center gap-1">
              <div className="w-full relative" style={{ height: '120px' }}>
                <div
                  className="absolute bottom-0 w-full rounded-t-sm bg-[#58a6ff] transition-all duration-500 hover:bg-[#4a96ef]"
                  style={{ height: `${(item.count / maxCount) * 100}%`, minHeight: item.count > 0 ? '4px' : '2px' }}
                  title={`${item.date}: ${item.count}`}
                />
              </div>
              <span className="text-[10px] text-muted-foreground whitespace-nowrap">
                {item.date.split('-').slice(1).join('/')}
              </span>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}

function PieChart({
  data,
  label,
}: {
  data: { type: string; count: number }[]
  label: string
}) {
  const total = data.reduce((s, d) => s + d.count, 0)
  const colors = ['#58a6ff', '#3fb950', '#d29922', '#f85149', '#bc8cff', '#f78166']

  const gradientParts = data.reduce<{ result: string; cumulative: number }>(
    (acc, item, i) => {
      const start = acc.cumulative
      const end = acc.cumulative + (item.count / total) * 360
      const color = colors[i % colors.length]
      acc.result += (acc.result ? ', ' : '') + `${color} ${start}deg ${end}deg`
      acc.cumulative = end
      return acc
    },
    { result: '', cumulative: 0 }
  )

  return (
    <Card className="bg-card border-border">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium">{label}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex flex-col sm:flex-row items-center gap-4">
          {/* CSS donut chart */}
          <div className="relative w-28 h-28 rounded-full flex-shrink-0" style={{
            background: `conic-gradient(${gradientParts.result})`,
          }}>
            <div className="absolute inset-3 rounded-full bg-card flex items-center justify-center">
              <span className="text-lg font-bold text-foreground">{total}</span>
            </div>
          </div>
          {/* Legend */}
          <div className="flex flex-wrap gap-2 justify-center sm:justify-start">
            {data.map((item, i) => (
              <div key={i} className="flex items-center gap-1.5 text-xs">
                <div
                  className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                  style={{ backgroundColor: colors[i % colors.length] }}
                />
                <span className="text-muted-foreground">
                  {item.type} ({item.count})
                </span>
              </div>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function PriorityChart({ data }: { data: { priority: string; count: number }[] }) {
  const maxCount = Math.max(...data.map((d) => d.count), 1)
  const colorMap: Record<string, string> = {
    high: '#f85149',
    medium: '#d29922',
    low: '#8899aa',
  }
  const labelMap: Record<string, string> = {
    high: 'Высокий',
    medium: 'Средний',
    low: 'Низкий',
  }

  return (
    <Card className="bg-card border-border">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium">По приоритету</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-3">
          {data.map((item) => (
            <div key={item.priority} className="flex items-center gap-3">
              <span className="text-xs text-muted-foreground w-16">{labelMap[item.priority] || item.priority}</span>
              <div className="flex-1 h-5 rounded-full bg-secondary overflow-hidden">
                <div
                  className="h-full rounded-full transition-all duration-500"
                  style={{
                    width: `${(item.count / maxCount) * 100}%`,
                    backgroundColor: colorMap[item.priority] || '#8899aa',
                    minWidth: item.count > 0 ? '8px' : '0px',
                  }}
                />
              </div>
              <span className="text-xs font-medium text-foreground w-8 text-right">{item.count}</span>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}

export default function DashboardPage() {
  const [stats, setStats] = useState<Stats | null>(null)
  const [news, setNews] = useState<NewsItem[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const controller = new AbortController()
    let cancelled = false

    const fetchData = async () => {
      setLoading(true)
      try {
        const [statsRes, newsRes] = await Promise.all([
          fetch('/api/stats?_t=' + Date.now(), { signal: controller.signal }),
          fetch('/api/news?limit=3&_t=' + Date.now(), { signal: controller.signal }),
        ])
        if (cancelled) return
        if (statsRes.ok) {
          const statsData = await statsRes.json()
          setStats(statsData)
        }
        if (newsRes.ok) {
          const newsData = await newsRes.json()
          setNews(newsData.news || newsData || [])
        }
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return
        console.error('Failed to fetch dashboard data:', err)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    fetchData()

    return () => {
      cancelled = true
      controller.abort()
    }
  }, [])

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-foreground">Обзор</h1>
        <p className="text-muted-foreground text-sm mt-1">Статистика мониторинга новостей DayZ</p>
      </div>

      {/* Stats cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard title="Всего новостей" value={stats?.total_news || 0} icon={Newspaper} color="#58a6ff" loading={loading} />
        <StatCard title="Опубликовано" value={stats?.published || 0} icon={CheckCircle} color="#3fb950" loading={loading} />
        <StatCard title="Ожидают" value={stats?.pending || 0} icon={Clock} color="#d29922" loading={loading} />
        <StatCard title="Ошибки" value={stats?.errors || 0} icon={AlertTriangle} color="#f85149" loading={loading} />
      </div>

      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-1">
          {stats ? (
            <BarChart data={stats.news_by_day} label="Новости за 7 дней" />
          ) : (
            <Skeleton className="h-52 bg-secondary rounded-xl" />
          )}
        </div>
        <div className="lg:col-span-1">
          {stats ? (
            <PieChart data={stats.news_by_type} label="По типу" />
          ) : (
            <Skeleton className="h-52 bg-secondary rounded-xl" />
          )}
        </div>
        <div className="lg:col-span-1">
          {stats ? (
            <PriorityChart data={stats.news_by_priority} />
          ) : (
            <Skeleton className="h-52 bg-secondary rounded-xl" />
          )}
        </div>
      </div>

      {/* Recent news - Telegram-style cards */}
      <div>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-medium text-foreground">Последние новости</h2>
          <Link href="/dashboard/news" className="text-xs text-[#58a6ff] hover:text-[#4a96ef] transition-colors flex items-center gap-1">
            Все новости <Eye className="w-3 h-3" />
          </Link>
        </div>
        {loading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4" style={{minWidth:0}}>
            {Array.from({ length: 3 }).map((_, i) => (
              <Card key={i} className="bg-[#1e2a4a] border-[#2d3a54]">
                <CardContent className="p-4 space-y-3">
                  <div className="flex items-center gap-2">
                    <Skeleton className="h-4 w-24 bg-[#2a3555]" />
                    <Skeleton className="h-3 w-20 bg-[#2a3555]" />
                    <Skeleton className="h-5 w-16 bg-[#2a3555] ml-auto" />
                  </div>
                  <div className="flex gap-2">
                    <Skeleton className="h-5 w-16 bg-[#2a3555]" />
                    <Skeleton className="h-5 w-16 bg-[#2a3555]" />
                  </div>
          <div className="rounded-xl bg-[#0e1621] overflow-hidden w-full">
                    <Skeleton className="h-6 bg-[#2b5278] w-full" />
                    <div className="p-3 space-y-2">
                      <Skeleton className="h-4 w-32 bg-[#2a3555]" />
                      <Skeleton className="h-4 w-full bg-[#182533]" />
                      <Skeleton className="h-4 w-3/4 bg-[#182533]" />
                      <Skeleton className="h-4 w-1/2 bg-[#182533]" />
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        ) : news.length === 0 ? (
          <Card className="bg-card border-border">
            <CardContent className="py-16 text-center">
              <Newspaper className="w-12 h-12 text-muted-foreground/30 mx-auto mb-3" />
              <p className="text-muted-foreground">Нет новостей</p>
            </CardContent>
          </Card>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4" style={{minWidth:0}}>
            {news.map((item) => {
              const postContent = item.formatted_post || item.ai_summary || item.original_text || 'Нет содержимого'
              const previewTime = new Date(item.created_at).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
              const images: string[] = (() => {
                try { return JSON.parse(item.images || '[]') } catch { return [] }
              })()

              return (
                <Card key={item.id} className="bg-[#1e2a4a] border-[#2d3a54] transition-all hover:border-[#58a6ff]/20" style={{minWidth:0,overflow:'hidden'}}>
                  <CardContent className="p-4 space-y-3">
                    {/* Top bar: source info + badges */}
                    <div className="flex items-center justify-between">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-xs text-[#8899aa] font-medium">{item.source_name}</span>
                        <span className="text-[11px] text-[#6c7b8f] flex items-center gap-1">
                          <Clock className="w-3 h-3" />
                          {formatTimestamp(item.created_at)}
                        </span>
                      </div>
                      <StatusBadge status={item.status} />
                    </div>

                    {/* Badges */}
                    <div className="flex flex-wrap items-center gap-2">
                      <NewsTypeBadge type={item.news_type} />
                      <PriorityBadge priority={item.priority} />
                    </div>

                    {/* Telegram Preview */}
                    <TelegramPreview
                      text={postContent}
                      images={images}
                      time={previewTime}
                    />
                  </CardContent>
                </Card>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
