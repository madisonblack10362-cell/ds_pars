'use client'

import { sanitizeTelegramHtml } from '@/lib/sanitize'
import { useState, useEffect, useCallback } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { SourceTypeBadge, SOURCE_TYPES } from '@/components/source-type-badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import {
  Search,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  Eye,
  EyeOff,
  Trash2,
  MessageSquare,
  ImageIcon,
  Video,
  Clock,
  Plus,
  Database,
  CheckSquare,
  Square,
  X,
} from 'lucide-react'
import Link from 'next/link'
import { useToast } from '@/hooks/use-toast'
import { formatTimestamp } from '@/lib/msk-time'

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

// ─── Telegram HTML → plain text ───
function telegramHtmlToText(html: string): string {
  let text = html
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/p>/gi, '\n')
    .replace(/<\/div>/gi, '\n')
    .replace(/<\/li>/gi, '\n')
    .replace(/<li[^>]*>/gi, '  • ')
    .replace(/<\/blockquote>/gi, '\n')
    .replace(/<blockquote>/gi, '')
    .replace(/<b[^>]*>|<strong[^>]*>/gi, '')
    .replace(/<\/b>|<\/strong>/gi, '')
    .replace(/<i[^>]*>|<em[^>]*>/gi, '')
    .replace(/<\/i>|<\/em>/gi, '')
    .replace(/<u[^>]*>/gi, '')
    .replace(/<\/u>/gi, '')
    .replace(/<s[^>]*>|<strike[^>]*>|<del[^>]*>/gi, '')
    .replace(/<\/s>|<\/strike>|<\/del>/gi, '')
    .replace(/<code[^>]*>/gi, '')
    .replace(/<\/code>/gi, '')
    .replace(/<pre[^>]*>/gi, '')
    .replace(/<\/pre>/gi, '')
    .replace(/<a[^>]*href=["']([^"']*)["'][^>]*>([^<]*)<\/a>/gi, '$2')
    .replace(/<[^>]+>/g, '')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&nbsp;/g, ' ')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
  return text
}

// ─── Badge Components ───
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

// ─── Telegram Preview Component (same as moderation) ───
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
    <div className="mt-3 rounded-xl overflow-hidden border border-[#2d3a54] w-full shadow-lg shadow-black/20" style={{minWidth:0}}>
      {/* TG top bar */}
      <div className="bg-[#2b5278] px-3 py-2 flex items-center gap-3">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" className="text-white/60 flex-shrink-0">
          <path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z" fill="currentColor"/>
        </svg>
        <div className="flex-1 min-w-0">
          <p className="text-[13px] font-semibold text-white truncate">DayZ Monitor</p>
          <p className="text-[11px] text-white/60">канал</p>
        </div>
        <div className="flex items-center gap-2 text-white/60">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
          </svg>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="5" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="12" cy="19" r="1"/>
          </svg>
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
          <span className="text-[11px] text-[#6c7b8f]">
            {time}
          </span>
          <svg className="w-4 h-3 text-[#6c7b8f]" viewBox="0 0 16 11" fill="none">
            <path d="M11.071 0L4.5 6.571 1.429 3.5 0 4.929 4.5 9.429 12.5 1.429z" fill="currentColor"/>
          </svg>
        </div>
      </div>
    </div>
  )
}

// ─── News Card with TG preview ───
function TelegramNewsCard({
  item,
  onViewDetails,
  onDelete,
  selectMode = false,
  selected = false,
  onToggleSelect,
}: {
  item: NewsItem
  onViewDetails: (item: NewsItem) => void
  onDelete: (id: number) => void
  selectMode?: boolean
  selected?: boolean
  onToggleSelect?: (id: number) => void
}) {
  const [showPreview, setShowPreview] = useState(true)
  const postContent = item.formatted_post || item.ai_summary || item.original_text || 'Нет содержимого'
  const previewTime = new Date(item.created_at).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })

  const images: string[] = (() => {
    try { return JSON.parse(item.images || '[]') } catch { return [] }
  })()

  return (
    <Card className={`bg-[#1e2a4a] border-[#2d3a54] transition-all hover:border-[#58a6ff]/20 ${selected ? 'ring-2 ring-[#58a6ff]/40 border-[#58a6ff]/30' : ''}`} style={{minWidth:0,overflow:'hidden'}}>
      <CardContent className="p-3 sm:p-4 lg:p-5 space-y-3" style={{minWidth:0,overflow:'hidden'}}>
        {/* Top bar: source info + badges + checkbox */}
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          {selectMode && (
            <button
              onClick={() => onToggleSelect?.(item.id)}
              className="flex-shrink-0 p-0.5 rounded hover:bg-[#2d3a54] transition-colors"
            >
              {selected ? (
                <CheckSquare className="w-5 h-5 text-[#58a6ff]" />
              ) : (
                <Square className="w-5 h-5 text-[#6c7b8f]" />
              )}
            </button>
          )}
          <SourceTypeBadge type={item.source_type} />
          <span className="text-xs text-[#8899aa] font-medium truncate max-w-[160px] sm:max-w-none">{item.source_name}</span>
          <span className="text-[11px] text-[#6c7b8f] flex items-center gap-1 flex-shrink-0">
            <Clock className="w-3 h-3" />
            {new Date(item.created_at).toLocaleString('ru-RU', {
              day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'
            })}
          </span>
        </div>

        {/* Badges */}
        <div className="flex flex-wrap items-center gap-2">
          <NewsTypeBadge type={item.news_type} />
          <PriorityBadge priority={item.priority} />
          <StatusBadge status={item.status} />
        </div>

        {/* Telegram Preview */}
        {showPreview && (
          <TelegramPreview
            text={postContent}
            images={images}
            time={previewTime}
          />
        )}

        {/* Action buttons */}
        <div className="flex flex-wrap items-center gap-1.5 sm:gap-2">
          <Button
            variant="ghost"
            size="sm"
            className="text-[#6c7b8f] hover:text-[#58a6ff] h-8 px-2"
            onClick={() => setShowPreview(!showPreview)}
            title={showPreview ? 'Скрыть предпросмотр' : 'Показать предпросмотр'}
          >
            {showPreview ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="border-[#2d3a54] text-[#8899aa] hover:text-foreground h-8 px-3"
            onClick={() => onViewDetails(item)}
          >
            <Eye className="w-3.5 h-3.5 mr-1.5" />
            Подробнее
          </Button>
          <div className="flex-1" />
          <Button
            size="sm"
            className="bg-red-500/10 text-red-400 border border-red-500/20 hover:bg-red-500/20 h-8 px-3"
            onClick={() => onDelete(item.id)}
          >
            <Trash2 className="w-3.5 h-3.5 mr-1.5" />
            Удалить
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

// ─── Skeleton ───
function NewsCardSkeleton() {
  return (
    <Card className="bg-[#1e2a4a] border-[#2d3a54]">
      <CardContent className="p-5 space-y-3">
        <div className="flex items-center gap-2">
          <Skeleton className="h-5 w-16 bg-[#2a3555]" />
          <Skeleton className="h-4 w-24 bg-[#2a3555]" />
          <Skeleton className="h-3 w-20 bg-[#2a3555]" />
        </div>
        <div className="flex gap-2">
          <Skeleton className="h-5 w-16 bg-[#2a3555]" />
          <Skeleton className="h-5 w-16 bg-[#2a3555]" />
          <Skeleton className="h-5 w-20 bg-[#2a3555]" />
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
  )
}

// ─── Main News Page ───
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
  const [deleteConfirmId, setDeleteConfirmId] = useState<number | null>(null)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [selectMode, setSelectMode] = useState(false)
  const [dbDialogOpen, setDbDialogOpen] = useState(false)
  const [dbStats, setDbStats] = useState<{total: number, byStatus: {status: string, count: number}[], bySource: {source: string, count: number}[]} | null>(null)
  const [bulkDeleteOpen, setBulkDeleteOpen] = useState(false)
  const pageSize = 20
  const { toast } = useToast()

  const fetchNews = useCallback(async (signal?: AbortSignal) => {
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

      const res = await fetch(`/api/news?${params}&_t=${Date.now()}`, { signal })
      if (res.ok) {
        const data = await res.json()
        setNews(data.news || [])
        setTotalPages(data.totalPages || 1)
      } else {
        console.error('News API error:', res.status, await res.text().catch(() => ''))
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return
      console.error('Failed to fetch news:', err)
    } finally {
      setLoading(false)
    }
  }, [search, sourceType, newsType, priority, status, page])

  useEffect(() => {
    const controller = new AbortController()
    fetchNews(controller.signal)
    return () => controller.abort()
  }, [fetchNews])

  const resetFilters = () => {
    setSearch('')
    setSourceType('all')
    setNewsType('all')
    setPriority('all')
    setStatus('all')
    setPage(1)
  }

  const toggleSelect = (id: number) => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const selectAll = () => {
    if (selectedIds.size === news.length) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(news.map(n => n.id)))
    }
  }

  const handleBulkDelete = async () => {
    try {
      let ok = 0
      for (const id of selectedIds) {
        const res = await fetch(`/api/news?id=${id}`, { method: 'DELETE' })
        if (res.ok) ok++
      }
      toast({ title: 'Удалено', description: `Удалено ${ok} из ${selectedIds.size} новостей` })
      setSelectedIds(new Set())
      setSelectMode(false)
      setBulkDeleteOpen(false)
      fetchNews()
    } catch {
      toast({ title: 'Ошибка', description: 'Не удалось удалить новости', variant: 'destructive' })
    }
  }

  const openDbDialog = async () => {
    setDbDialogOpen(true)
    try {
      const [allRes, pendingRes] = await Promise.all([
        fetch(`/api/news?status=all&limit=1&_t=${Date.now()}`),
        fetch(`/api/news?status=pending&limit=1&_t=${Date.now()}`),
        fetch(`/api/news?status=published&limit=1&_t=${Date.now()}`),
        fetch(`/api/news?status=rejected&limit=1&_t=${Date.now()}`),
        fetch(`/api/news?status=approved&limit=1&_t=${Date.now()}`),
        fetch(`/api/news?status=scheduled&limit=1&_t=${Date.now()}`),
      ])
      const statuses = ['pending', 'published', 'rejected', 'approved', 'scheduled']
      const statusCounts = await Promise.all(statuses.map(async (s, i) => {
        const d = await allRes[i]?.json?.() ?? {}
        return { status: s, count: d.total ?? 0 }
      }))
      const totalData = await pendingRes.json()
      setDbStats({
        total: totalData.total ?? 0,
        byStatus: statusCounts,
        bySource: [],
      })
    } catch {
      console.error('Failed to fetch DB stats')
    }
  }

  const handleDelete = async (id: number) => {
    try {
      const res = await fetch(`/api/news?id=${id}`, { method: 'DELETE' })
      if (res.ok) {
        toast({ title: 'Удалено', description: 'Новость удалена из базы данных' })
        setDeleteConfirmId(null)
        fetchNews()
      } else {
        toast({ title: 'Ошибка', description: 'Не удалось удалить новость', variant: 'destructive' })
      }
    } catch {
      toast({ title: 'Ошибка', description: 'Не удалось удалить новость', variant: 'destructive' })
    }
    setDeleteConfirmId(null)
  }

  return (
    <div className="space-y-4 sm:space-y-5 min-w-0">
      {/* Header */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <h1 className="text-xl sm:text-2xl font-bold text-foreground truncate">Лента новостей</h1>
          <p className="text-[#8899aa] text-xs sm:text-sm mt-0.5">Все собранные новости из источников</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Link href="/dashboard/create">
            <Button
              size="sm"
              className="gap-1.5 h-8 px-3 text-[#0d1117] font-medium"
              style={{ background: 'linear-gradient(135deg, #58a6ff, #3a8ae0)' }}
            >
              <Plus className="w-4 h-4" />
              Создать
            </Button>
          </Link>
          <Button
            variant="outline"
            size="sm"
            className="border-[#2d3a54] text-[#8899aa] hover:text-foreground h-8 px-2.5 sm:px-3"
            onClick={() => fetchNews()}
            disabled={loading}
          >
            <RefreshCw className={`w-4 h-4 mr-2 ${loading ? 'animate-spin' : ''}`} />
            Обновить
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="border-[#2d3a54] text-[#8899aa] hover:text-foreground h-8 px-2.5 sm:px-3"
            onClick={openDbDialog}
          >
            <Database className="w-4 h-4 mr-2" />
            База данных
          </Button>
          {selectMode ? (
            <>
              <Button
                variant="outline"
                size="sm"
                className="border-[#2d3a54] text-[#8899aa] hover:text-foreground h-8 px-2.5 sm:px-3"
                onClick={selectAll}
              >
                {selectedIds.size === news.length ? <CheckSquare className="w-4 h-4 mr-2" /> : <Square className="w-4 h-4 mr-2" />}
                {selectedIds.size === news.length ? 'Снять всё' : 'Выбрать всё'}
              </Button>
              {selectedIds.size > 0 && (
                <Button
                  size="sm"
                  className="bg-red-500/15 text-red-400 border border-red-500/20 hover:bg-red-500/25 h-8 px-3"
                  onClick={() => setBulkDeleteOpen(true)}
                >
                  <Trash2 className="w-4 h-4 mr-2" />
                  Удалить ({selectedIds.size})
                </Button>
              )}
              <Button
                variant="ghost"
                size="sm"
                className="text-[#6c7b8f] hover:text-foreground h-8 px-2"
                onClick={() => { setSelectMode(false); setSelectedIds(new Set()) }}
              >
                <X className="w-4 h-4" />
              </Button>
            </>
          ) : (
            <Button
              variant="outline"
              size="sm"
              className="border-[#2d3a54] text-[#8899aa] hover:text-foreground h-8 px-2.5 sm:px-3"
              onClick={() => setSelectMode(true)}
            >
              <Trash2 className="w-4 h-4 mr-2" />
              Удаление
            </Button>
          )}
        </div>
      </div>

      {/* Filters */}
      <Card className="bg-[#1e2a4a] border-[#2d3a54]">
        <CardContent className="p-3 sm:p-4 min-w-0">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-6 gap-2 sm:gap-3 min-w-0">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#6c7b8f]" />
              <Input
                placeholder="Поиск..."
                value={search}
                onChange={(e) => { setSearch(e.target.value); setPage(1) }}
                className="pl-9 bg-[#151525] border-[#2d3a54] text-foreground placeholder:text-[#6c7b8f]"
              />
            </div>
            <Select value={sourceType} onValueChange={(v) => { setSourceType(v); setPage(1) }}>
              <SelectTrigger className="w-full bg-[#151525] border-[#2d3a54] text-foreground">
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
              <SelectTrigger className="w-full bg-[#151525] border-[#2d3a54] text-foreground">
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
              <SelectTrigger className="w-full bg-[#151525] border-[#2d3a54] text-foreground">
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
              <SelectTrigger className="w-full bg-[#151525] border-[#2d3a54] text-foreground">
                <SelectValue placeholder="Статус" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Все</SelectItem>
                <SelectItem value="pending">Ожидает</SelectItem>
                <SelectItem value="approved">Одобрена</SelectItem>
                <SelectItem value="published">Опубликована</SelectItem>
              </SelectContent>
            </Select>
            <Button variant="outline" onClick={resetFilters} className="border-[#2d3a54] text-[#8899aa] hover:text-foreground">
              Сбросить
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* News list */}
      {loading ? (
        <div className="space-y-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <NewsCardSkeleton key={i} />
          ))}
        </div>
      ) : news.length === 0 ? (
        <Card className="bg-[#1e2a4a] border-[#2d3a54]">
          <CardContent className="py-16 text-center">
            <p className="text-[#8899aa]">Нет новостей для отображения</p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 sm:gap-4" style={{minWidth:0}}>
          {news.map((item) => (
            <TelegramNewsCard
              key={item.id}
              item={item}
              onViewDetails={setSelectedNews}
              onDelete={setDeleteConfirmId}
              selectMode={selectMode}
              selected={selectedIds.has(item.id)}
              onToggleSelect={toggleSelect}
            />
          ))}
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2">
          <Button
            variant="outline"
            size="icon"
            className="border-[#2d3a54] text-[#8899aa] hover:text-foreground h-8 w-8"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
          >
            <ChevronLeft className="w-4 h-4" />
          </Button>
          <span className="text-sm text-[#8899aa]">
            {page} / {totalPages}
          </span>
          <Button
            variant="outline"
            size="icon"
            className="border-[#2d3a54] text-[#8899aa] hover:text-foreground h-8 w-8"
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
          >
            <ChevronRight className="w-4 h-4" />
          </Button>
        </div>
      )}

      {/* Detail dialog */}
      <Dialog open={!!selectedNews} onOpenChange={() => setSelectedNews(null)}>
        <DialogContent className="bg-[#1e2a4a] border-[#2d3a54] max-w-[calc(100vw-2rem)] sm:max-w-2xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="text-foreground">Детали новости</DialogTitle>
          </DialogHeader>
          {selectedNews && (
            <div className="space-y-4">
              {/* Header */}
              <div className="flex items-center gap-3 pb-3 border-b border-[#2d3a54]">
                <div className="w-10 h-10 rounded-full bg-[#58a6ff]/20 flex items-center justify-center flex-shrink-0 border-2 border-[#58a6ff]/30">
                  <MessageSquare className="w-5 h-5 text-[#58a6ff]" />
                </div>
                <div>
                  <p className="text-sm font-semibold text-[#58a6ff]">DayZ Monitor</p>
                  <p className="text-xs text-[#6c7b8f]">{formatTimestamp(selectedNews.created_at)}</p>
                </div>
              </div>

              {/* Badges */}
              <div className="flex flex-wrap gap-2">
                <SourceTypeBadge type={selectedNews.source_type} />
                <NewsTypeBadge type={selectedNews.news_type} />
                <PriorityBadge priority={selectedNews.priority} />
                <StatusBadge status={selectedNews.status} />
              </div>

              <div>
                <p className="text-xs text-[#6c7b8f] mb-1">Источник</p>
                <p className="text-sm text-foreground">{selectedNews.source_name}</p>
              </div>

              {/* Formatted post preview */}
              {selectedNews.formatted_post && (
                <div>
                  <p className="text-xs text-[#6c7b8f] mb-2">Форматированный пост</p>
                  <TelegramPreview
                    text={selectedNews.formatted_post}
                    images={(() => { try { return JSON.parse(selectedNews.images || '[]') } catch { return [] } })()}
                    time={new Date(selectedNews.created_at).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}
                  />
                </div>
              )}

              {selectedNews.ai_summary && (
                <div>
                  <p className="text-xs text-[#6c7b8f] mb-1">AI Сводка</p>
                  <div className="bg-[#151525] rounded-lg p-3 text-sm text-[#c8d6e5] whitespace-pre-wrap leading-relaxed">
                    {selectedNews.ai_summary}
                  </div>
                </div>
              )}

              <div>
                <p className="text-xs text-[#6c7b8f] mb-1">Оригинальный текст</p>
                <div className="bg-[#151525] rounded-lg p-3 text-sm text-[#8899aa] whitespace-pre-wrap">
                  {selectedNews.original_text}
                </div>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

          {/* Database stats dialog */}
      <Dialog open={dbDialogOpen} onOpenChange={setDbDialogOpen}>
        <DialogContent className="bg-[#1e2a4a] border-[#2d3a54] max-w-md">
          <DialogHeader>
            <DialogTitle className="text-foreground flex items-center gap-2">
              <Database className="w-5 h-5 text-[#58a6ff]" />
              База данных новостей
            </DialogTitle>
          </DialogHeader>
          {dbStats ? (
            <div className="space-y-4">
              <div className="bg-[#151525] rounded-lg p-4 text-center">
                <p className="text-3xl font-bold text-[#58a6ff]">{dbStats.total}</p>
                <p className="text-sm text-[#8899aa] mt-1">Всего новостей в базе</p>
              </div>
              <div className="space-y-2">
                {dbStats.byStatus.map(item => {
                  const labels: Record<string, {label: string, color: string}> = {
                    pending: { label: 'Ожидают', color: 'text-yellow-400' },
                    published: { label: 'Опубликовано', color: 'text-[#58a6ff]' },
                    rejected: { label: 'Отклонено', color: 'text-red-400' },
                    approved: { label: 'Одобрено', color: 'text-green-400' },
                    scheduled: { label: 'В расписании', color: 'text-purple-400' },
                  }
                  const info = labels[item.status] || { label: item.status, color: 'text-[#8899aa]' }
                  return (
                    <div key={item.status} className="flex items-center justify-between bg-[#151525] rounded-lg px-4 py-2.5">
                      <span className={`text-sm font-medium ${info.color}`}>{info.label}</span>
                      <span className="text-sm text-foreground font-semibold">{item.count}</span>
                    </div>
                  )
                })}
              </div>
            </div>
          ) : (
            <div className="py-8 text-center text-[#8899aa]">Загрузка...</div>
          )}
        </DialogContent>
      </Dialog>

      {/* Bulk delete confirmation */}
      <AlertDialog open={bulkDeleteOpen} onOpenChange={setBulkDeleteOpen}>
        <AlertDialogContent className="bg-[#1e2a4a] border-[#2d3a54]">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-foreground">Удалить {selectedIds.size} новостей?</AlertDialogTitle>
            <AlertDialogDescription className="text-[#8899aa]">
              {selectedIds.size} новостей будут полностью удалены из базы данных. Это действие нельзя отменить.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="border-[#2d3a54] text-[#8899aa] hover:text-foreground">Отмена</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleBulkDelete}
              className="bg-red-500/15 text-red-400 hover:bg-red-500/25 border-0"
            >
              Удалить всё
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

  {/* Delete confirmation */}
      <AlertDialog open={!!deleteConfirmId} onOpenChange={() => setDeleteConfirmId(null)}>
        <AlertDialogContent className="bg-[#1e2a4a] border-[#2d3a54]">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-foreground">Удалить новость?</AlertDialogTitle>
            <AlertDialogDescription className="text-[#8899aa]">
              Новость будет полностью удалена из базы данных. Это действие нельзя отменить.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="border-[#2d3a54] text-[#8899aa] hover:text-foreground">Отмена</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => { if (deleteConfirmId) handleDelete(deleteConfirmId) }}
              className="bg-red-500/15 text-red-400 hover:bg-red-500/25 border-0"
            >
              Удалить
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
