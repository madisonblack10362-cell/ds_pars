'use client'

import { useState, useEffect, useCallback } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Search,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  ChevronUp,
  Loader2,
  RefreshCw,
} from 'lucide-react'

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
  created_at: string
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

function SourceTypeBadge({ type }: { type: string }) {
  const config: Record<string, { label: string; className: string }> = {
    discord: { label: 'Discord', className: 'bg-indigo-500/15 text-indigo-400 border-indigo-500/30' },
    telegram: { label: 'Telegram', className: 'bg-sky-500/15 text-sky-400 border-sky-500/30' },
    vk: { label: 'VK', className: 'bg-blue-500/15 text-blue-400 border-blue-500/30' },
    website: { label: 'Сайт', className: 'bg-teal-500/15 text-teal-400 border-teal-500/30' },
  }
  const c = config[type] || { label: type, className: 'bg-secondary text-muted-foreground border-border' }
  return <Badge variant="outline" className={c.className}>{c.label}</Badge>
}

export default function NewsPage() {
  const [news, setNews] = useState<NewsItem[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [sourceType, setSourceType] = useState('all')
  const [newsType, setNewsType] = useState('all')
  const [priority, setPriority] = useState('all')
  const [status, setStatus] = useState('all')
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [selectedNews, setSelectedNews] = useState<NewsItem | null>(null)
  const pageSize = 20

  const fetchNews = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams({
        limit: String(pageSize),
        offset: String((page - 1) * pageSize),
      })
      if (search) params.set('search', search)
      if (sourceType !== 'all') params.set('source_type', sourceType)
      if (newsType !== 'all') params.set('news_type', newsType)
      if (priority !== 'all') params.set('priority', priority)
      if (status !== 'all') params.set('status', status)

      const res = await fetch(`/api/news?${params}`)
      if (res.ok) {
        const data = await res.json()
        setNews(data.news || [])
        setTotalPages(data.totalPages || 1)
      }
    } catch (err) {
      console.error('Failed to fetch news:', err)
    } finally {
      setLoading(false)
    }
  }, [search, sourceType, newsType, priority, status, page])

  useEffect(() => {
    fetchNews()
  }, [fetchNews])

  const resetFilters = () => {
    setSearch('')
    setSourceType('all')
    setNewsType('all')
    setPriority('all')
    setStatus('all')
    setPage(1)
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Лента новостей</h1>
          <p className="text-muted-foreground text-sm mt-1">Все собранные новости из источников</p>
        </div>
        <Button
          variant="outline"
          size="sm"
          className="border-border text-muted-foreground hover:text-foreground"
          onClick={fetchNews}
          disabled={loading}
        >
          <RefreshCw className={`w-4 h-4 mr-2 ${loading ? 'animate-spin' : ''}`} />
          Обновить
        </Button>
      </div>

      {/* Filters */}
      <Card className="bg-card border-border">
        <CardContent className="p-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-6 gap-3">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
              <Input
                placeholder="Поиск..."
                value={search}
                onChange={(e) => { setSearch(e.target.value); setPage(1) }}
                className="pl-9 bg-secondary border-border text-foreground placeholder:text-muted-foreground"
              />
            </div>
            <Select value={sourceType} onValueChange={(v) => { setSourceType(v); setPage(1) }}>
              <SelectTrigger className="w-full bg-secondary border-border text-foreground">
                <SelectValue placeholder="Источник" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Все источники</SelectItem>
                <SelectItem value="discord">Discord</SelectItem>
                <SelectItem value="telegram">Telegram</SelectItem>
                <SelectItem value="vk">VK</SelectItem>
                <SelectItem value="website">Сайт</SelectItem>
              </SelectContent>
            </Select>
            <Select value={newsType} onValueChange={(v) => { setNewsType(v); setPage(1) }}>
              <SelectTrigger className="w-full bg-secondary border-border text-foreground">
                <SelectValue placeholder="Тип" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Все типы</SelectItem>
                <SelectItem value="wipe">Вайп</SelectItem>
                <SelectItem value="update">Обновление</SelectItem>
                <SelectItem value="patch">Патч</SelectItem>
                <SelectItem value="event">Событие</SelectItem>
                <SelectItem value="maintenance">Обслуживание</SelectItem>
                <SelectItem value="other">Другое</SelectItem>
              </SelectContent>
            </Select>
            <Select value={priority} onValueChange={(v) => { setPriority(v); setPage(1) }}>
              <SelectTrigger className="w-full bg-secondary border-border text-foreground">
                <SelectValue placeholder="Приоритет" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Все</SelectItem>
                <SelectItem value="high">Высокий</SelectItem>
                <SelectItem value="medium">Средний</SelectItem>
                <SelectItem value="low">Низкий</SelectItem>
              </SelectContent>
            </Select>
            <Select value={status} onValueChange={(v) => { setStatus(v); setPage(1) }}>
              <SelectTrigger className="w-full bg-secondary border-border text-foreground">
                <SelectValue placeholder="Статус" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Все</SelectItem>
                <SelectItem value="pending">Ожидает</SelectItem>
                <SelectItem value="approved">Одобрена</SelectItem>
                <SelectItem value="published">Опубликована</SelectItem>
                <SelectItem value="rejected">Отклонена</SelectItem>
              </SelectContent>
            </Select>
            <Button variant="outline" onClick={resetFilters} className="border-border text-muted-foreground hover:text-foreground">
              Сбросить
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* News table */}
      <Card className="bg-card border-border">
        <CardContent className="p-0">
          <div className="max-h-[600px] overflow-y-auto">
            <Table>
              <TableHeader>
                <TableRow className="border-border hover:bg-transparent">
                  <TableHead className="text-muted-foreground">Источник</TableHead>
                  <TableHead className="text-muted-foreground hidden sm:table-cell">Тип</TableHead>
                  <TableHead className="text-muted-foreground">Приоритет</TableHead>
                  <TableHead className="text-muted-foreground hidden md:table-cell">Текст</TableHead>
                  <TableHead className="text-muted-foreground">Статус</TableHead>
                  <TableHead className="text-muted-foreground hidden lg:table-cell">Дата</TableHead>
                  <TableHead className="text-muted-foreground w-10"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {loading ? (
                  Array.from({ length: 10 }).map((_, i) => (
                    <TableRow key={i} className="border-border">
                      <TableCell><Skeleton className="h-4 w-24 bg-secondary" /></TableCell>
                      <TableCell className="hidden sm:table-cell"><Skeleton className="h-5 w-16 bg-secondary" /></TableCell>
                      <TableCell><Skeleton className="h-5 w-16 bg-secondary" /></TableCell>
                      <TableCell className="hidden md:table-cell"><Skeleton className="h-4 w-48 bg-secondary" /></TableCell>
                      <TableCell><Skeleton className="h-5 w-20 bg-secondary" /></TableCell>
                      <TableCell className="hidden lg:table-cell"><Skeleton className="h-4 w-20 bg-secondary" /></TableCell>
                      <TableCell><Skeleton className="h-4 w-4 bg-secondary" /></TableCell>
                    </TableRow>
                  ))
                ) : news.length === 0 ? (
                  <TableRow className="border-border">
                    <TableCell colSpan={7} className="text-center py-12 text-muted-foreground">
                      Нет новостей для отображения
                    </TableCell>
                  </TableRow>
                ) : (
                  news.map((item) => (
                    <TableRow
                      key={item.id}
                      className="border-border cursor-pointer hover:bg-secondary/50"
                      onClick={() => setSelectedNews(item)}
                    >
                      <TableCell>
                        <div className="flex flex-col gap-1">
                          <span className="text-xs text-foreground">{item.source_name}</span>
                          <SourceTypeBadge type={item.source_type} />
                        </div>
                      </TableCell>
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
                      <TableCell>
                        <ChevronRight className="w-4 h-4 text-muted-foreground" />
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2">
          <Button
            variant="outline"
            size="icon"
            className="border-border text-muted-foreground hover:text-foreground h-8 w-8"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
          >
            <ChevronLeft className="w-4 h-4" />
          </Button>
          <span className="text-sm text-muted-foreground">
            {page} / {totalPages}
          </span>
          <Button
            variant="outline"
            size="icon"
            className="border-border text-muted-foreground hover:text-foreground h-8 w-8"
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
          >
            <ChevronRight className="w-4 h-4" />
          </Button>
        </div>
      )}

      {/* Detail dialog */}
      <Dialog open={!!selectedNews} onOpenChange={() => setSelectedNews(null)}>
        <DialogContent className="bg-card border-border max-w-2xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="text-foreground">Детали новости</DialogTitle>
          </DialogHeader>
          {selectedNews && (
            <div className="space-y-4">
              <div className="flex flex-wrap gap-2">
                <SourceTypeBadge type={selectedNews.source_type} />
                <NewsTypeBadge type={selectedNews.news_type} />
                <PriorityBadge priority={selectedNews.priority} />
                <StatusBadge status={selectedNews.status} />
              </div>
              <div>
                <p className="text-xs text-muted-foreground mb-1">Источник</p>
                <p className="text-sm text-foreground">{selectedNews.source_name}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground mb-1">Дата</p>
                <p className="text-sm text-foreground">
                  {new Date(selectedNews.created_at).toLocaleString('ru-RU')}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground mb-1">Оригинальный текст</p>
                <div className="bg-secondary rounded-lg p-3 text-sm text-foreground whitespace-pre-wrap">
                  {selectedNews.original_text}
                </div>
              </div>
              {selectedNews.ai_summary && (
                <div>
                  <p className="text-xs text-muted-foreground mb-1">AI Сводка</p>
                  <div className="bg-secondary rounded-lg p-3 text-sm text-foreground whitespace-pre-wrap">
                    {selectedNews.ai_summary}
                  </div>
                </div>
              )}
              {selectedNews.formatted_post && (
                <div>
                  <p className="text-xs text-muted-foreground mb-1">Форматированный пост</p>
                  <div className="bg-secondary rounded-lg p-3 text-sm text-foreground whitespace-pre-wrap">
                    {selectedNews.formatted_post}
                  </div>
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
