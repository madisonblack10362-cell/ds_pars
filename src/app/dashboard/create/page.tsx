'use client'

import { sanitizeTelegramHtml } from '@/lib/sanitize'
import { useState, useRef, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import {
  Upload,
  X,
  Image as ImageIcon,
  Video,
  Plus,
  Trash2,
  Eye,
  EyeOff,
  Send,
  Save,
  Loader2,
  MessageSquare,
  Clock,
  Zap,
} from 'lucide-react'
import { useToast } from '@/hooks/use-toast'

const NEWS_TYPES = [
  { value: 'other', label: 'Новость', icon: '📰', color: '#58a6ff' },
  { value: 'wipe', label: 'Вайп', icon: '⚠️', color: '#f85149' },
  { value: 'update', label: 'Обновление', icon: '🔥', color: '#f0883e' },
  { value: 'event', label: 'Ивент', icon: '🎯', color: '#a371f7' },
  { value: 'maintenance', label: 'Техработы', icon: '🔧', color: '#d29922' },
  { value: 'server_open', label: 'Открытие сервера', icon: '🟢', color: '#3fb950' },
  { value: 'new_season', label: 'Новый сезон', icon: '🌟', color: '#db61a2' },
  { value: 'content_add', label: 'Новый контент', icon: '✨', color: '#79c0ff' },
  { value: 'bugfix', label: 'Исправления', icon: '🐛', color: '#8b949e' },
  { value: 'balance_change', label: 'Баланс', icon: '⚖️', color: '#d2a8ff' },
  { value: 'mod_update', label: 'Моды', icon: '🔄', color: '#56d4dd' },
  { value: 'important_announcement', label: 'Анонс', icon: '📢', color: '#f85149' },
]

const PRIORITIES = [
  { value: 'high', label: 'Высокий', color: '#f85149', bg: 'bg-[#f85149]/15 text-[#f85149] border-[#f85149]/30' },
  { value: 'medium', label: 'Средний', color: '#d29922', bg: 'bg-[#d29922]/15 text-[#d29922] border-[#d29922]/30' },
  { value: 'low', label: 'Низкий', color: '#8b949e', bg: 'bg-[#8b949e]/15 text-[#8b949e] border-[#8b949e]/30' },
]

// ─── Telegram HTML → rich HTML for preview bubble ───
function telegramHtmlToRich(html: string): string {
  return html
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
  return sanitizeTelegramHtml(html)
}

// ─── Telegram Preview Component ───
function TelegramPreview({
  text,
  images,
}: {
  text: string
  images: string[]
}) {
  const richHtml = telegramHtmlToRich(text)
  const displayImage = images.length > 0 ? images[0] : null
  const now = new Date()
  const time = now.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })

  if (!text) return null

  return (
    <div className="rounded-xl overflow-hidden border border-[#2d3a54] w-full shadow-lg shadow-black/20">
      {/* TG top bar */}
      <div className="bg-[#2b5278] px-3 py-2 flex items-center gap-3">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" className="text-white/60 flex-shrink-0">
          <path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z" fill="currentColor"/>
        </svg>
        <div className="flex-1 min-w-0">
          <p className="text-[13px] font-semibold text-white truncate">DayZ HUB</p>
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
      <div className="bg-[#0e1621] px-3 pb-3 pt-1 overflow-x-hidden">
        {/* Channel avatar + name */}
        <div className="flex items-center gap-2.5 mb-2">
          <div className="w-10 h-10 rounded-full bg-[#58a6ff]/20 flex items-center justify-center flex-shrink-0 border-2 border-[#58a6ff]/30">
            <MessageSquare className="w-5 h-5 text-[#58a6ff]" />
          </div>
          <div className="min-w-0">
            <p className="text-sm font-semibold text-[#58a6ff]">DayZ HUB</p>
            <p className="text-[11px] text-[#6c7b8f]">канал</p>
          </div>
        </div>

        {/* Media preview */}
        {displayImage && (
          <div className="mb-1.5 overflow-hidden rounded-md max-h-[300px] bg-[#1a2733]">
            <img
              src={displayImage}
              alt=""
              className="w-full max-w-full object-cover"
              loading="lazy"
              style={{ maxHeight: 300 }}
              onError={(e) => {
                (e.target as HTMLImageElement).style.display = 'none'
              }}
            />
          </div>
        )}

        {/* Message bubble */}
        <div className="inline-block bg-[#182533] rounded-xl rounded-tl-sm px-2.5 py-2 max-w-full break-words">
          <div
            className="text-sm text-[#f5f5f5] leading-[1.45] telegram-preview-content break-words"
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

export default function CreateNewsPage() {
  const router = useRouter()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [loading, setLoading] = useState(false)
  const [publishingNow, setPublishingNow] = useState(false)
  const [showPreview, setShowPreview] = useState(true)
  const { toast } = useToast()

  const [form, setForm] = useState({
    title: '',
    content: '',
    summary: '',
    newsType: 'other',
    priority: 'medium',
    serverName: '',
    author: '',
  })

  const [media, setMedia] = useState<{ url: string; type: 'image' | 'video'; filename: string }[]>([])
  const [uploading, setUploading] = useState(false)
  const [links, setLinks] = useState<string[]>([''])

  const updateForm = (key: string, value: string) => {
    setForm((prev) => ({ ...prev, [key]: value }))
  }

  const handleFiles = useCallback(async (files: FileList | null) => {
    if (!files || files.length === 0) return

    setUploading(true)
    try {
      const formData = new FormData()
      Array.from(files).forEach((f) => formData.append('files', f))

      const token = localStorage.getItem('auth_token')
      const res = await fetch('/api/upload', {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: formData,
      })

      if (!res.ok) {
        const err = await res.json()
        toast({ title: 'Ошибка', description: err.error || 'Ошибка загрузки', variant: 'destructive' })
        return
      }

      const data = await res.json()
      setMedia((prev) => [
        ...prev,
        ...data.files.map((f: { url: string; type: string; filename: string }) => ({
          url: f.url,
          type: f.type as 'image' | 'video',
          filename: f.filename,
        })),
      ])
    } catch {
      toast({ title: 'Ошибка', description: 'Ошибка загрузки файлов', variant: 'destructive' })
    } finally {
      setUploading(false)
    }
  }, [toast])

  const removeMedia = (index: number) => {
    setMedia((prev) => prev.filter((_, i) => i !== index))
  }

  const addLink = () => setLinks((prev) => [...prev, ''])
  const removeLink = (index: number) => setLinks((prev) => prev.filter((_, i) => i !== index))
  const updateLink = (index: number, value: string) => {
    setLinks((prev) => prev.map((l, i) => (i === index ? value : l)))
  }

  const buildFormattedPost = () => {
    const typeLabel = currentType?.label || 'Новость'
    const typeIcon = currentType?.icon || '📰'

    // Заголовок — если заполнен, используем его
    const headline = form.title ? form.title : `${prioIcon} ${typeIcon} ${typeLabel.toUpperCase()}`
    let text = `<b>${headline}</b>\n\n`

    if (form.serverName) text += `Сервер: <b>${form.serverName}</b>\n`
    if (form.author) text += `Автор: <i>${form.author}</i>\n`

    const body = form.summary || form.content
    if (body) {
      text += `\n<blockquote>${body}</blockquote>\n`
    }

    const validLinks = links.filter((l) => l.trim())
    if (validLinks.length > 0) {
      text += '\n'
      validLinks.forEach((l) => {
        text += `🔗 <a href="${l}">${l}</a>\n`
      })
    }

    text += '\n#dayz #новости'
    return text
  }

  // Создать + опубликовать сразу (минуя расписание)
  const handlePublishNow = async () => {
    if (!form.title && !form.content) return
    setPublishingNow(true)
    try {
      const token = localStorage.getItem('auth_token')
      const imageUrls = media.filter((m) => m.type === 'image').map((m) => m.url)
      const videoUrls = media.filter((m) => m.type === 'video').map((m) => m.url)
      const allMediaUrls = [...imageUrls, ...videoUrls]
      const validLinks = links.filter((l) => l.trim())
      const formattedPost = buildFormattedPost()

      const res = await fetch('/api/news/create', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          ...form,
          formattedPost,
          status: 'approved',
          images: allMediaUrls,
          links: validLinks,
        }),
      })

      if (!res.ok) {
        const err = await res.json()
        toast({ title: 'Ошибка', description: err.error || 'Ошибка создания', variant: 'destructive' })
        return
      }

      const data = await res.json()
      if (data.news_id) {
        // Публикуем сразу — минуя расписание
        await fetch(`/api/news/${data.news_id}/publish`, {
          method: 'POST',
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        })
      }

      toast({ title: 'Опубликовано', description: 'Новость отправлена немедленно' })
      router.push('/dashboard/news')
    } catch {
      toast({ title: 'Ошибка', description: 'Не удалось опубликовать', variant: 'destructive' })
    } finally {
      setPublishingNow(false)
    }
  }

  // Сохранить как черновик (попадёт в расписание при одобрении)
  const handleSaveDraft = async () => {
    if (!form.title && !form.content) return
    setLoading(true)
    try {
      const token = localStorage.getItem('auth_token')
      const imageUrls = media.filter((m) => m.type === 'image').map((m) => m.url)
      const videoUrls = media.filter((m) => m.type === 'video').map((m) => m.url)
      const allMediaUrls = [...imageUrls, ...videoUrls]
      const validLinks = links.filter((l) => l.trim())
      const formattedPost = buildFormattedPost()

      const res = await fetch('/api/news/create', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          ...form,
          formattedPost,
          status: 'pending',
          images: allMediaUrls,
          links: validLinks,
        }),
      })

      if (!res.ok) {
        const err = await res.json()
        toast({ title: 'Ошибка', description: err.error || 'Ошибка создания', variant: 'destructive' })
        return
      }

      toast({ title: 'Сохранено', description: 'Черновик отправлен на модерацию' })
      router.push('/dashboard/news')
    } catch {
      toast({ title: 'Ошибка', description: 'Не удалось сохранить', variant: 'destructive' })
    } finally {
      setLoading(false)
    }
  }

  const currentType = NEWS_TYPES.find((t) => t.value === form.newsType)
  const currentPrio = PRIORITIES.find((p) => p.value === form.priority)
  const accentColor = currentType?.color || '#58a6ff'
  const prioIcon = form.priority === 'high' ? '🔴' : form.priority === 'medium' ? '🟡' : '⚪'

  const previewImages = media.map((m) => m.url)
  const formattedPost = buildFormattedPost()

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      handleFiles(e.dataTransfer.files)
    },
    [handleFiles]
  )

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
  }

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div
            className="w-12 h-12 rounded-xl flex items-center justify-center text-2xl"
            style={{ backgroundColor: accentColor + '20' }}
          >
            {currentType?.icon || '📰'}
          </div>
          <div>
            <h1 className="text-2xl font-bold" style={{ color: accentColor }}>
              {currentType?.label || 'Создать новость'}
            </h1>
            <p className="text-muted-foreground text-sm mt-0.5">
              Ручная публикация с фото и видео
            </p>
          </div>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => setShowPreview(!showPreview)}
          className="border-[#2d3a54] text-[#8899aa] hover:text-foreground hover:border-[#58a6ff]/40"
        >
          {showPreview ? <EyeOff className="w-4 h-4 mr-1" /> : <Eye className="w-4 h-4 mr-1" />}
          Превью
        </Button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Main form */}
        <div className="lg:col-span-2 space-y-5">
          {/* Title */}
          <Card className="border-l-4" style={{ borderLeftColor: accentColor }}>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium">Заголовок</CardTitle>
            </CardHeader>
            <CardContent>
              <Input
                placeholder="Заголовок новости..."
                value={form.title}
                onChange={(e) => updateForm('title', e.target.value)}
                className="text-base"
              />
            </CardContent>
          </Card>

          {/* Content */}
          <Card className="border-l-4" style={{ borderLeftColor: accentColor }}>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium">Содержание</CardTitle>
            </CardHeader>
            <CardContent>
              <Textarea
                placeholder="Текст новости..."
                value={form.content}
                onChange={(e) => updateForm('content', e.target.value)}
                rows={6}
              />
            </CardContent>
          </Card>

          {/* Summary */}
          <Card className="border-l-4" style={{ borderLeftColor: accentColor }}>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium">Краткое описание</CardTitle>
            </CardHeader>
            <CardContent>
              <Textarea
                placeholder="Краткое резюме (опционально)..."
                value={form.summary}
                onChange={(e) => updateForm('summary', e.target.value)}
                rows={3}
              />
            </CardContent>
          </Card>

          {/* Media Upload */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium flex items-center gap-2">
                <ImageIcon className="w-4 h-4" />
                Фото и видео
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* Drop zone */}
              <div
                className="border-2 border-dashed border-muted-foreground/30 rounded-lg p-8 text-center cursor-pointer hover:border-[#58a6ff]/50 hover:bg-[#58a6ff]/5 transition-colors"
                onClick={() => fileInputRef.current?.click()}
                onDrop={handleDrop}
                onDragOver={handleDragOver}
              >
                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  accept="image/*,video/*"
                  className="hidden"
                  onChange={(e) => handleFiles(e.target.files)}
                />
                {uploading ? (
                  <div className="flex flex-col items-center gap-2">
                    <Loader2 className="w-8 h-8 animate-spin text-[#58a6ff]" />
                    <p className="text-sm text-muted-foreground">Загрузка...</p>
                  </div>
                ) : (
                  <div className="flex flex-col items-center gap-2">
                    <Upload className="w-8 h-8 text-muted-foreground" />
                    <p className="text-sm text-muted-foreground">
                      Перетащите фото или видео сюда, или нажмите для выбора
                    </p>
                    <p className="text-xs text-muted-foreground/60">
                      JPG, PNG, GIF, WebP, MP4, WebM — до 50MB
                    </p>
                  </div>
                )}
              </div>

              {/* Media preview grid */}
              {media.length > 0 && (
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                  {media.map((item, idx) => (
                    <div
                      key={idx}
                      className="relative group rounded-lg overflow-hidden bg-muted aspect-video"
                    >
                      {item.type === 'video' ? (
                        <video
                          src={item.url}
                          className="w-full h-full object-cover"
                          muted
                        />
                      ) : (
                        <img
                          src={item.url}
                          alt={item.filename}
                          className="w-full h-full object-cover"
                        />
                      )}
                      <div className="absolute inset-0 bg-black/0 group-hover:bg-black/40 transition-colors" />
                      <Badge
                        variant="secondary"
                        className="absolute top-1 left-1 text-[10px] px-1.5"
                      >
                        {item.type === 'video' ? (
                          <><Video className="w-3 h-3 mr-0.5" /> Видео</>
                        ) : (
                          <><ImageIcon className="w-3 h-3 mr-0.5" /> Фото</>
                        )}
                      </Badge>
                      <Button
                        variant="destructive"
                        size="icon"
                        className="absolute top-1 right-1 w-6 h-6 opacity-0 group-hover:opacity-100 transition-opacity"
                        onClick={() => removeMedia(idx)}
                      >
                        <X className="w-3 h-3" />
                      </Button>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Links */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium flex items-center justify-between">
                Ссылки
                <Button variant="ghost" size="sm" onClick={addLink}>
                  <Plus className="w-3 h-3 mr-1" /> Добавить
                </Button>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {links.map((link, idx) => (
                <div key={idx} className="flex items-center gap-2">
                  <Input
                    placeholder="https://..."
                    value={link}
                    onChange={(e) => updateLink(idx, e.target.value)}
                  />
                  {links.length > 1 && (
                    <Button
                      variant="ghost"
                      size="icon"
                      className="shrink-0"
                      onClick={() => removeLink(idx)}
                    >
                      <Trash2 className="w-4 h-4" />
                    </Button>
                  )}
                </div>
              ))}
            </CardContent>
          </Card>
        </div>

        {/* Sidebar */}
        <div className="space-y-5">
          {/* Type & Priority */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium">Параметры</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <label className="text-xs text-muted-foreground mb-1 block">
                  Тип новости
                </label>
                <Select
                  value={form.newsType}
                  onValueChange={(v) => updateForm('newsType', v)}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {NEWS_TYPES.map((t) => (
                      <SelectItem key={t.value} value={t.value}>
                        {t.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div>
                <label className="text-xs text-muted-foreground mb-1 block">
                  Приоритет
                </label>
                <div className="flex gap-2">
                  {PRIORITIES.map((p) => (
                    <Button
                      key={p.value}
                      variant={form.priority === p.value ? 'default' : 'outline'}
                      size="sm"
                      className={form.priority === p.value
                        ? 'border ' + p.bg
                        : ''
                      }
                      onClick={() => updateForm('priority', p.value)}
                    >
                      {p.label}
                    </Button>
                  ))}
                </div>
              </div>

              <Separator />

              <div>
                <label className="text-xs text-muted-foreground mb-1 block">
                  Сервер
                </label>
                <Input
                  placeholder="Название сервера"
                  value={form.serverName}
                  onChange={(e) => updateForm('serverName', e.target.value)}
                />
              </div>

              <div>
                <label className="text-xs text-muted-foreground mb-1 block">
                  Автор
                </label>
                <Input
                  placeholder="Автор новости"
                  value={form.author}
                  onChange={(e) => updateForm('author', e.target.value)}
                />
              </div>
            </CardContent>
          </Card>

          {/* Action buttons */}
          <Card className="border" style={{ borderColor: accentColor + '40' }}>
            <CardContent className="pt-6 space-y-3">
              <Button
                className="w-full gap-2"
                style={{ backgroundColor: accentColor }}
                disabled={publishingNow || (!form.title && !form.content)}
                onClick={handlePublishNow}
              >
                {publishingNow ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Zap className="w-4 h-4" />
                )}
                Опубликовать сразу
              </Button>
              <p className="text-[11px] text-center text-muted-foreground/60">
                Без расписания, немедленная отправка
              </p>
              <Separator />
              <Button
                variant="outline"
                className="w-full gap-2"
                disabled={loading || (!form.title && !form.content)}
                onClick={handleSaveDraft}
              >
                {loading ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Clock className="w-4 h-4" />
                )}
                В очередь на расписание
              </Button>
              <p className="text-[11px] text-center text-muted-foreground/60">
                Черновик попадёт в модерацию и затем в расписание
              </p>
            </CardContent>
          </Card>

          {/* Telegram Preview */}
          {showPreview && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-medium flex items-center gap-2">
                  <MessageSquare className="w-4 h-4 text-[#58a6ff]" />
                  Превью Telegram
                </CardTitle>
              </CardHeader>
              <CardContent>
                {formattedPost ? (
                  <TelegramPreview text={formattedPost} images={previewImages} />
                ) : (
                  <div className="text-sm text-muted-foreground text-center py-8">
                    Начните вводить текст для превью
                  </div>
                )}
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  )
}
