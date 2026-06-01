'use client'

import { useState, useEffect } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  Newspaper,
  CheckCircle,
  Clock,
  Database,
  AlertTriangle,
} from 'lucide-react'

interface Stats {
  total_news: number
  published: number
  pending: number
  sources: number
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
  created_at: string
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
    const fetchData = async () => {
      try {
        const [statsRes, newsRes] = await Promise.all([
          fetch('/api/stats'),
          fetch('/api/news?limit=10'),
        ])
        if (statsRes.ok) {
          const statsData = await statsRes.json()
          setStats(statsData)
        }
        if (newsRes.ok) {
          const newsData = await newsRes.json()
          setNews(newsData.news || newsData || [])
        }
      } catch (err) {
        console.error('Failed to fetch dashboard data:', err)
      } finally {
        setLoading(false)
      }
    }
    fetchData()
  }, [])

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-foreground">Обзор</h1>
        <p className="text-muted-foreground text-sm mt-1">Статистика мониторинга новостей DayZ</p>
      </div>

      {/* Stats cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
        <StatCard title="Всего новостей" value={stats?.total_news || 0} icon={Newspaper} color="#58a6ff" loading={loading} />
        <StatCard title="Опубликовано" value={stats?.published || 0} icon={CheckCircle} color="#3fb950" loading={loading} />
        <StatCard title="Ожидают" value={stats?.pending || 0} icon={Clock} color="#d29922" loading={loading} />
        <StatCard title="Источники" value={stats?.sources || 0} icon={Database} color="#bc8cff" loading={loading} />
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

      {/* Recent news table */}
      <Card className="bg-card border-border">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-medium">Последние новости</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <div className="max-h-96 overflow-y-auto">
            <Table>
              <TableHeader>
                <TableRow className="border-border hover:bg-transparent">
                  <TableHead className="text-muted-foreground">Источник</TableHead>
                  <TableHead className="text-muted-foreground hidden sm:table-cell">Тип</TableHead>
                  <TableHead className="text-muted-foreground">Приоритет</TableHead>
                  <TableHead className="text-muted-foreground hidden md:table-cell">Текст</TableHead>
                  <TableHead className="text-muted-foreground">Статус</TableHead>
                  <TableHead className="text-muted-foreground hidden lg:table-cell">Дата</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {loading ? (
                  Array.from({ length: 5 }).map((_, i) => (
                    <TableRow key={i} className="border-border">
                      <TableCell><Skeleton className="h-4 w-24 bg-secondary" /></TableCell>
                      <TableCell className="hidden sm:table-cell"><Skeleton className="h-5 w-16 bg-secondary" /></TableCell>
                      <TableCell><Skeleton className="h-5 w-16 bg-secondary" /></TableCell>
                      <TableCell className="hidden md:table-cell"><Skeleton className="h-4 w-48 bg-secondary" /></TableCell>
                      <TableCell><Skeleton className="h-5 w-20 bg-secondary" /></TableCell>
                      <TableCell className="hidden lg:table-cell"><Skeleton className="h-4 w-20 bg-secondary" /></TableCell>
                    </TableRow>
                  ))
                ) : news.length === 0 ? (
                  <TableRow className="border-border">
                    <TableCell colSpan={6} className="text-center py-8 text-muted-foreground">
                      Нет новостей
                    </TableCell>
                  </TableRow>
                ) : (
                  news.map((item) => (
                    <TableRow key={item.id} className="border-border">
                      <TableCell className="text-foreground text-xs">{item.source_name}</TableCell>
                      <TableCell className="hidden sm:table-cell">
                        <NewsTypeBadge type={item.news_type} />
                      </TableCell>
                      <TableCell>
                        <PriorityBadge priority={item.priority} />
                      </TableCell>
                      <TableCell className="hidden md:table-cell max-w-xs">
                        <p className="text-xs text-muted-foreground truncate">{item.original_text}</p>
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={item.status} />
                      </TableCell>
                      <TableCell className="hidden lg:table-cell text-xs text-muted-foreground">
                        {new Date(item.created_at).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
