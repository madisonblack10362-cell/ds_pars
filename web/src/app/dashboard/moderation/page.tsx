'use client'

import { useState, useEffect, useCallback } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Checkbox } from '@/components/ui/checkbox'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
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
  CheckCircle,
  XCircle,
  Pencil,
  ShieldCheck,
  ShieldX,
  RefreshCw,
  Loader2,
  SquareCheck,
} from 'lucide-react'
import { useToast } from '@/hooks/use-toast'

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

export default function ModerationPage() {
  const [news, setNews] = useState<NewsItem[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [editingItem, setEditingItem] = useState<NewsItem | null>(null)
  const [editText, setEditText] = useState('')
  const [editLoading, setEditLoading] = useState(false)
  const [confirmAction, setConfirmAction] = useState<{ type: 'bulk-approve' | 'bulk-reject' } | null>(null)
  const { toast } = useToast()

  const fetchNews = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch('/api/news?status=pending&limit=50')
      if (res.ok) {
        const data = await res.json()
        setNews(data.news || [])
      }
    } catch (err) {
      console.error('Failed to fetch pending news:', err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchNews()
  }, [fetchNews])

  const toggleSelect = (id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleSelectAll = () => {
    if (selectedIds.size === news.length) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(news.map((n) => n.id)))
    }
  }

  const handleAction = async (id: number, action: 'approve' | 'reject') => {
    try {
      const res = await fetch(`/api/moderation`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ news_id: id, action }),
      })
      if (res.ok) {
        toast({
          title: action === 'approve' ? 'Новость одобрена' : 'Новость отклонена',
          description: action === 'approve' ? 'Новость отправлена на публикацию' : 'Новость отклонена',
        })
        fetchNews()
      }
    } catch {
      toast({
        title: 'Ошибка',
        description: 'Не удалось выполнить действие',
        variant: 'destructive',
      })
    }
  }

  const handleEdit = (item: NewsItem) => {
    setEditingItem(item)
    setEditText(item.formatted_post || item.ai_summary || item.original_text)
  }

  const handleSaveEdit = async () => {
    if (!editingItem) return
    setEditLoading(true)
    try {
      const res = await fetch(`/api/moderation`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ news_id: editingItem.id, formatted_post: editText }),
      })
      if (res.ok) {
        toast({ title: 'Сохранено', description: 'Пост отредактирован' })
        setEditingItem(null)
        fetchNews()
      }
    } catch {
      toast({ title: 'Ошибка', description: 'Не удалось сохранить', variant: 'destructive' })
    } finally {
      setEditLoading(false)
    }
  }

  const handleBulkAction = async (action: 'approve' | 'reject') => {
    try {
      const res = await fetch(`/api/moderation`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ news_ids: Array.from(selectedIds), action }),
      })
      if (res.ok) {
        toast({
          title: action === 'approve' ? 'Новости одобрены' : 'Новости отклонены',
          description: `Обработано ${selectedIds.size} новостей`,
        })
        setSelectedIds(new Set())
        fetchNews()
      }
    } catch {
      toast({ title: 'Ошибка', description: 'Не удалось выполнить массовое действие', variant: 'destructive' })
    }
    setConfirmAction(null)
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Модерация</h1>
          <p className="text-muted-foreground text-sm mt-1">
            Очередь новостей, ожидающих модерации ({news.length})
          </p>
        </div>
        <div className="flex items-center gap-2">
          {selectedIds.size > 0 && (
            <>
              <Button
                size="sm"
                className="bg-green-500/15 text-green-400 border border-green-500/30 hover:bg-green-500/25"
                onClick={() => setConfirmAction({ type: 'bulk-approve' })}
              >
                <ShieldCheck className="w-4 h-4 mr-1" />
                Одобрить ({selectedIds.size})
              </Button>
              <Button
                size="sm"
                className="bg-red-500/15 text-red-400 border border-red-500/30 hover:bg-red-500/25"
                onClick={() => setConfirmAction({ type: 'bulk-reject' })}
              >
                <ShieldX className="w-4 h-4 mr-1" />
                Отклонить ({selectedIds.size})
              </Button>
            </>
          )}
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
      </div>

      {/* News cards */}
      {loading ? (
        <div className="space-y-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <Card key={i} className="bg-card border-border">
              <CardContent className="p-6">
                <Skeleton className="h-4 w-32 bg-secondary mb-3" />
                <Skeleton className="h-3 w-full bg-secondary mb-2" />
                <Skeleton className="h-3 w-3/4 bg-secondary mb-3" />
                <div className="flex gap-2">
                  <Skeleton className="h-8 w-20 bg-secondary" />
                  <Skeleton className="h-8 w-20 bg-secondary" />
                  <Skeleton className="h-8 w-20 bg-secondary" />
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : news.length === 0 ? (
        <Card className="bg-card border-border">
          <CardContent className="p-12 text-center">
            <ShieldCheck className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
            <p className="text-muted-foreground">Нет новостей для модерации</p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {/* Select all */}
          <div className="flex items-center gap-2 px-2">
            <Checkbox
              checked={selectedIds.size === news.length && news.length > 0}
              onCheckedChange={toggleSelectAll}
              className="border-border"
            />
            <span className="text-xs text-muted-foreground">Выбрать все</span>
          </div>

          {news.map((item) => (
            <Card key={item.id} className="bg-card border-border transition-colors hover:border-[#58a6ff]/30">
              <CardContent className="p-4 lg:p-6 space-y-4">
                <div className="flex items-start gap-3">
                  <Checkbox
                    checked={selectedIds.has(item.id)}
                    onCheckedChange={() => toggleSelect(item.id)}
                    className="border-border mt-1"
                  />
                  <div className="flex-1 min-w-0">
                    {/* Header badges */}
                    <div className="flex flex-wrap items-center gap-2 mb-3">
                      <span className="text-xs text-muted-foreground">{item.source_name}</span>
                      <Badge variant="outline" className="bg-secondary text-muted-foreground border-border">
                        {new Date(item.created_at).toLocaleString('ru-RU')}
                      </Badge>
                      <NewsTypeBadge type={item.news_type} />
                      <PriorityBadge priority={item.priority} />
                    </div>

                    {/* Original text */}
                    <div className="mb-3">
                      <p className="text-xs text-muted-foreground mb-1">Оригинальный текст</p>
                      <div className="bg-secondary rounded-lg p-3 text-sm text-foreground whitespace-pre-wrap max-h-32 overflow-y-auto">
                        {item.original_text}
                      </div>
                    </div>

                    {/* AI Summary */}
                    {item.ai_summary && (
                      <div className="mb-3">
                        <p className="text-xs text-muted-foreground mb-1">AI Сводка</p>
                        <div className="bg-[#58a6ff]/5 border border-[#58a6ff]/10 rounded-lg p-3 text-sm text-foreground whitespace-pre-wrap">
                          {item.ai_summary}
                        </div>
                      </div>
                    )}

                    {/* Formatted post preview */}
                    {item.formatted_post && (
                      <div className="mb-3">
                        <p className="text-xs text-muted-foreground mb-1">Предпросмотр поста</p>
                        <div className="bg-green-500/5 border border-green-500/10 rounded-lg p-3 text-sm text-foreground whitespace-pre-wrap max-h-32 overflow-y-auto">
                          {item.formatted_post}
                        </div>
                      </div>
                    )}

                    {/* Actions */}
                    <div className="flex flex-wrap gap-2">
                      <Button
                        size="sm"
                        className="bg-green-500/15 text-green-400 border border-green-500/30 hover:bg-green-500/25"
                        onClick={() => handleAction(item.id, 'approve')}
                      >
                        <CheckCircle className="w-4 h-4 mr-1" />
                        Одобрить
                      </Button>
                      <Button
                        size="sm"
                        className="bg-red-500/15 text-red-400 border border-red-500/30 hover:bg-red-500/25"
                        onClick={() => handleAction(item.id, 'reject')}
                      >
                        <XCircle className="w-4 h-4 mr-1" />
                        Отклонить
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        className="border-border text-muted-foreground hover:text-foreground"
                        onClick={() => handleEdit(item)}
                      >
                        <Pencil className="w-4 h-4 mr-1" />
                        Редактировать
                      </Button>
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Edit dialog */}
      <Dialog open={!!editingItem} onOpenChange={() => setEditingItem(null)}>
        <DialogContent className="bg-card border-border max-w-2xl">
          <DialogHeader>
            <DialogTitle className="text-foreground">Редактирование поста</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            {editingItem && (
              <>
                <div className="flex flex-wrap gap-2">
                  <NewsTypeBadge type={editingItem.news_type} />
                  <PriorityBadge priority={editingItem.priority} />
                  <Badge variant="outline" className="bg-secondary text-muted-foreground border-border">
                    {editingItem.source_name}
                  </Badge>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground mb-1">Оригинальный текст</p>
                  <div className="bg-secondary rounded-lg p-3 text-xs text-muted-foreground whitespace-pre-wrap max-h-24 overflow-y-auto">
                    {editingItem.original_text}
                  </div>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground mb-2">Форматированный пост</p>
                  <Textarea
                    value={editText}
                    onChange={(e) => setEditText(e.target.value)}
                    className="bg-secondary border-border text-foreground min-h-[200px] resize-y"
                  />
                </div>
              </>
            )}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              className="border-border text-muted-foreground hover:text-foreground"
              onClick={() => setEditingItem(null)}
            >
              Отмена
            </Button>
            <Button
              className="bg-[#58a6ff] hover:bg-[#4a96ef] text-primary-foreground"
              onClick={handleSaveEdit}
              disabled={editLoading}
            >
              {editLoading && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
              Сохранить
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Bulk action confirmation */}
      <AlertDialog open={!!confirmAction} onOpenChange={() => setConfirmAction(null)}>
        <AlertDialogContent className="bg-card border-border">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-foreground">
              {confirmAction?.type === 'bulk-approve' ? 'Массовое одобрение' : 'Массовое отклонение'}
            </AlertDialogTitle>
            <AlertDialogDescription className="text-muted-foreground">
              Вы уверены, что хотите {confirmAction?.type === 'bulk-approve' ? 'одобрить' : 'отклонить'} {selectedIds.size} новостей?
              Это действие нельзя отменить.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="border-border text-muted-foreground hover:text-foreground">Отмена</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (confirmAction) {
                  handleBulkAction(confirmAction.type === 'bulk-approve' ? 'approve' : 'reject')
                }
              }}
              className={confirmAction?.type === 'bulk-approve'
                ? 'bg-green-500/15 text-green-400 hover:bg-green-500/25 border-0'
                : 'bg-red-500/15 text-red-400 hover:bg-red-500/25 border-0'
              }
            >
              Подтвердить
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
