'use client'

import { sanitizeTelegramHtml } from '@/lib/sanitize'
import { useState, useEffect, useCallback, useRef } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { SourceTypeBadge } from '@/components/source-type-badge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Checkbox } from '@/components/ui/checkbox'
import { Skeleton } from '@/components/ui/skeleton'
import { Input } from '@/components/ui/input'
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
  ImageIcon,
  Video,
  X,
  Plus,
  Trash2,
  Eye,
  EyeOff,
  Upload,
  MessageSquare,
  Send,
} from 'lucide-react'
import { useToast } from '@/hooks/use-toast'
import { cn } from '@/lib/utils'

interface NewsItem {
  id: string
  source_name: string
  source_type: string
  news_type: string
  priority: string
  status: string
  original_text: string
  ai_summary: string
  formatted_post: string | null
  created_at: string
  images: string
  links: string
}

// ─── Telegram HTML → plain text (strips tags for clean display) ───
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

// ─── Telegram HTML → rich HTML for preview bubble (converts TG tags to styled HTML) ───
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

// ─── Telegram Preview Component ───
function TelegramPreview({
  text,
  images,
  time,
  showPreview,
  isMediaMessage = false,
}: {
  text: string
  images: string[]
  time: string
  showPreview: boolean
  isMediaMessage?: boolean
}) {
  if (!showPreview) return null

  const richHtml = telegramHtmlToRich(text)
  const plainText = telegramHtmlToText(text)
  const hasMedia = isMediaMessage || images.length > 0
  const displayImage = images[0] || null

  return (
    <div className="mt-4 rounded-xl overflow-hidden border border-[#2d3a54] w-full shadow-lg shadow-black/20">
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
      <div className="bg-[#0e1621] px-3 pb-3 pt-1 overflow-x-hidden">
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

// ─── Media Gallery Component ───
function MediaGallery({
  images,
  onRemove,
  onAdd,
  editable = false,
}: {
  images: string[]
  onRemove: (url: string) => void
  onAdd: (url: string) => void
  editable?: boolean
}) {
  const [newUrl, setNewUrl] = useState('')
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [uploading, setUploading] = useState(false)

  const handleAddUrl = () => {
    const url = newUrl.trim()
    if (url && (url.startsWith('http://') || url.startsWith('https://'))) {
      onAdd(url)
      setNewUrl('')
    }
  }

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    try {
      // Convert to base64 data URL
      const reader = new FileReader()
      reader.onload = () => {
        const dataUrl = reader.result as string
        onAdd(dataUrl)
        setUploading(false)
      }
      reader.onerror = () => setUploading(false)
      reader.readAsDataURL(file)
    } catch {
      setUploading(false)
    }
    // Reset input
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  if (images.length === 0 && !editable) return null

  return (
    <div className="space-y-2">
      {images.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {images.map((url, idx) => (
            <div key={idx} className="relative group rounded-lg overflow-hidden border border-[#2d3a54]">
              <img
                src={url}
                alt={`Медиа ${idx + 1}`}
                className="w-24 h-24 object-cover"
                onError={(e) => {
                  (e.target as HTMLImageElement).style.display = 'none'
                  const parent = (e.target as HTMLImageElement).parentElement
                  if (parent) {
                    parent.innerHTML = '<div class="w-24 h-24 flex items-center justify-center bg-[#2a3555] text-muted-foreground text-xs">Ошибка</div>'
                  }
                }}
              />
              {editable && (
                <button
                  onClick={() => onRemove(url)}
                  className="absolute top-1 right-1 w-5 h-5 rounded-full bg-red-500/80 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
                >
                  <X className="w-3 h-3 text-white" />
                </button>
              )}
              {url.startsWith('data:') && (
                <Badge variant="outline" className="absolute bottom-1 left-1 text-[9px] py-0 px-1 bg-black/60 border-0 text-white/80">
                  {url.startsWith('data:video') ? (
                    <><Video className="w-2.5 h-2.5 mr-0.5" />Видео</>
                  ) : (
                    <><ImageIcon className="w-2.5 h-2.5 mr-0.5" />Фото</>
                  )}
                </Badge>
              )}
            </div>
          ))}
        </div>
      )}

      {editable && (
        <div className="space-y-2">
          {/* URL input */}
          <div className="flex gap-2">
            <Input
              value={newUrl}
              onChange={(e) => setNewUrl(e.target.value)}
              placeholder="URL изображения или видео..."
              className="bg-[#1a1a2e] border-[#2d3a54] text-foreground text-sm h-8"
              onKeyDown={(e) => e.key === 'Enter' && handleAddUrl()}
            />
            <Button
              size="sm"
              variant="outline"
              className="border-[#2d3a54] text-muted-foreground hover:text-foreground h-8 px-3"
              onClick={handleAddUrl}
              disabled={!newUrl.trim()}
            >
              <Plus className="w-3.5 h-3.5" />
            </Button>
          </div>

          {/* File upload */}
          <div className="flex items-center gap-3">
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*,video/mp4,video/webm"
              className="hidden"
              onChange={handleFileUpload}
            />
            <Button
              size="sm"
              variant="outline"
              className="border-[#2d3a54] text-muted-foreground hover:text-foreground h-8"
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
            >
              {uploading ? (
                <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" />
              ) : (
                <Upload className="w-3.5 h-3.5 mr-1.5" />
              )}
              Загрузить файл
            </Button>
            <span className="text-[11px] text-muted-foreground">Фото (JPG, PNG, WebP) или видео (MP4, WebP)</span>
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Single News Card with inline editing and TG preview ───
function NewsCard({
  item,
  selected,
  onToggleSelect,
  onApprove,
  onReject,
  onEdit,
  onEditImages,
}: {
  item: NewsItem
  selected: boolean
  onToggleSelect: () => void
  onApprove: () => void
  onReject: () => void
  onEdit: (formatted_post: string) => void
  onEditImages: (images: string[]) => void
}) {
  const [showPreview, setShowPreview] = useState(true)
  const [isEditing, setIsEditing] = useState(false)
  const [editText, setEditText] = useState(item.formatted_post || item.ai_summary || item.original_text)
  const [images, setImages] = useState<string[]>(() => {
    try { return JSON.parse(item.images || '[]') } catch { return [] }
  })
  const [editImages, setEditImages] = useState(false)

  const previewText = isEditing ? editText : (item.formatted_post || item.ai_summary || item.original_text)
  const previewTime = new Date(item.created_at).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })

  const handleSaveEdit = () => {
    onEdit(editText)
    onEditImages(images)
    setIsEditing(false)
    setEditImages(false)
  }

  const handleCancelEdit = () => {
    setEditText(item.formatted_post || item.ai_summary || item.original_text)
    try { setImages(JSON.parse(item.images || '[]')) } catch { setImages([]) }
    setIsEditing(false)
    setEditImages(false)
  }

  const handleAddImage = (url: string) => {
    setImages(prev => [...prev, url])
  }

  const handleRemoveImage = (url: string) => {
    setImages(prev => prev.filter(u => u !== url))
  }

  return (
    <Card className="bg-[#1e2a4a] border-[#2d3a54] transition-all hover:border-[#58a6ff]/20">
      <CardContent className="p-4 lg:p-5 space-y-3">
        {/* Row 1: checkbox + badges + actions */}
        <div className="flex items-start gap-3">
          <Checkbox
            checked={selected}
            onCheckedChange={onToggleSelect}
            className="border-[#2d3a54] mt-1"
          />
          <div className="flex-1 min-w-0">
            {/* Top bar */}
            <div className="flex flex-wrap items-center gap-2 mb-1">
              <SourceTypeBadge type={item.source_type} />
              <span className="text-xs text-[#8899aa] font-medium">{item.source_name}</span>
              <span className="text-[11px] text-[#6c7b8f]">
                {new Date(item.created_at).toLocaleString('ru-RU', {
                  day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'
                })}
              </span>
              <NewsTypeBadge type={item.news_type} />
              <PriorityBadge priority={item.priority} />
            </div>

            {/* Original text (collapsible) */}
            <div className="mb-3">
              <button
                onClick={() => {
                  const el = document.getElementById(`orig-${item.id}`)
                  if (el) el.classList.toggle('hidden')
                }}
                className="text-[11px] text-[#6c7b8f] hover:text-[#8899aa] transition-colors flex items-center gap-1 mb-1"
              >
                <Eye className="w-3 h-3" />
                Оригинальный текст
              </button>
              <div id={`orig-${item.id}`} className="bg-[#151525] rounded-lg p-3 text-xs text-[#8899aa] whitespace-pre-wrap max-h-24 overflow-y-auto leading-relaxed">
                {item.original_text}
              </div>
            </div>

            {/* AI Summary (collapsible) */}
            {item.ai_summary && (
              <div className="mb-3">
                <button
                  onClick={() => {
                    const el = document.getElementById(`summary-${item.id}`)
                    if (el) el.classList.toggle('hidden')
                  }}
                  className="text-[11px] text-[#6c7b8f] hover:text-[#58a6ff] transition-colors flex items-center gap-1 mb-1"
                >
                  <MessageSquare className="w-3 h-3" />
                  AI Сводка
                </button>
                <div id={`summary-${item.id}`} className="bg-[#58a6ff]/5 border border-[#58a6ff]/10 rounded-lg p-3 text-xs text-[#c8d6e5] whitespace-pre-wrap leading-relaxed">
                  {item.ai_summary}
                </div>
              </div>
            )}

            {/* ─── EDITING MODE ─── */}
            {isEditing && (
              <div className="space-y-3 mb-3">
                <div>
                  <p className="text-[11px] text-[#58a6ff] font-medium mb-1.5 flex items-center gap-1">
                    <Pencil className="w-3 h-3" />
                    Редактирование поста
                  </p>
                  <Textarea
                    value={editText}
                    onChange={(e) => setEditText(e.target.value)}
                    className="bg-[#151525] border-[#2d3a54] text-[#f5f5f5] min-h-[160px] resize-y text-sm leading-relaxed focus:border-[#58a6ff]/50"
                    placeholder="Текст поста (поддерживается Telegram HTML: <b>, <i>, <code>, <a>, <blockquote>)"
                  />
                </div>

                {/* Media section */}
                <div>
                  <div className="flex items-center justify-between mb-1.5">
                    <button
                      onClick={() => setEditImages(!editImages)}
                      className="text-[11px] text-[#58a6ff] font-medium flex items-center gap-1"
                    >
                      <ImageIcon className="w-3 h-3" />
                      Медиа ({images.length})
                      {editImages ? <EyeOff className="w-3 h-3" /> : <Eye className="w-3 h-3" />}
                    </button>
                  </div>
                  {editImages && (
                    <MediaGallery
                      images={images}
                      onRemove={handleRemoveImage}
                      onAdd={handleAddImage}
                      editable={true}
                    />
                  )}
                </div>

                {/* Edit buttons */}
                <div className="flex items-center gap-2">
                  <Button
                    size="sm"
                    className="bg-[#58a6ff] hover:bg-[#4a96ef] text-[#0d1117] h-8"
                    onClick={handleSaveEdit}
                  >
                    <CheckCircle className="w-3.5 h-3.5 mr-1" />
                    Сохранить
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    className="border-[#2d3a54] text-[#8899aa] hover:text-[#f5f5f5] h-8"
                    onClick={handleCancelEdit}
                  >
                    Отмена
                  </Button>
                </div>
              </div>
            )}

            {/* ─── TELEGRAM PREVIEW ─── */}
            {!isEditing && (
              <TelegramPreview
                text={previewText}
                images={images}
                time={previewTime}
                showPreview={showPreview}
              />
            )}

            {/* ─── ACTION BUTTONS ─── */}
            {!isEditing && (
              <div className="flex flex-wrap gap-2 mt-1">
                <Button
                  size="sm"
                  className="bg-green-500/15 text-green-400 border border-green-500/30 hover:bg-green-500/25 h-8"
                  onClick={onApprove}
                >
                  <Send className="w-3.5 h-3.5 mr-1" />
                  Одобрить
                </Button>
                <Button
                  size="sm"
                  className="bg-red-500/15 text-red-400 border border-red-500/30 hover:bg-red-500/25 h-8"
                  onClick={onReject}
                >
                  <XCircle className="w-3.5 h-3.5 mr-1" />
                  Отклонить
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  className="border-[#2d3a54] text-[#8899aa] hover:text-[#f5f5f5] h-8"
                  onClick={() => setIsEditing(true)}
                >
                  <Pencil className="w-3.5 h-3.5 mr-1" />
                  Редактировать
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="text-[#6c7b8f] hover:text-[#58a6ff] h-8 px-2"
                  onClick={() => setShowPreview(!showPreview)}
                  title={showPreview ? 'Скрыть предпросмотр' : 'Показать предпросмотр'}
                >
                  {showPreview ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                </Button>
              </div>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

// ─── Main Moderation Page ───
export default function ModerationPage() {
  const [news, setNews] = useState<NewsItem[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [confirmAction, setConfirmAction] = useState<{ type: 'bulk-approve' | 'bulk-reject' } | null>(null)
  const [saveLoading, setSaveLoading] = useState<string | null>(null)
  const { toast } = useToast()

  const fetchNews = useCallback(async (signal?: AbortSignal) => {
    setLoading(true)
    try {
      const res = await fetch(`/api/news?status=pending&limit=50&_t=${Date.now()}`, { signal })
      if (res.ok) {
        const data = await res.json()
        setNews(data.news || [])
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return
      console.error('Failed to fetch pending news:', err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    fetchNews(controller.signal)
    return () => controller.abort()
  }, [fetchNews])

  const toggleSelect = (id: string) => {
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

  const handleAction = async (id: string, action: 'approve' | 'reject') => {
    try {
      const res = await fetch(`/api/moderation`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ news_id: id, action }),
      })
      if (res.ok) {
        toast({
          title: action === 'approve' ? 'Новость одобрена' : 'Новость отклонена',
          description: action === 'approve' ? 'Отправлена на публикацию по расписанию' : 'Новость отклонена',
        })
        fetchNews()
      }
    } catch {
      toast({ title: 'Ошибка', description: 'Не удалось выполнить действие', variant: 'destructive' })
    }
  }

  const handleEdit = async (id: string, formatted_post: string, images: string[]) => {
    setSaveLoading(id)
    try {
      const res = await fetch(`/api/moderation`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ news_id: id, formatted_post, images }),
      })
      if (res.ok) {
        toast({ title: 'Сохранено', description: 'Пост и медиа обновлены' })
        fetchNews()
      }
    } catch {
      toast({ title: 'Ошибка', description: 'Не удалось сохранить', variant: 'destructive' })
    } finally {
      setSaveLoading(null)
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
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Модерация</h1>
          <p className="text-[#8899aa] text-sm mt-1">
            Очередь новостей на модерации
            {news.length > 0 && (
              <span className="ml-1.5 px-2 py-0.5 rounded-full bg-[#58a6ff]/15 text-[#58a6ff] text-xs font-medium">
                {news.length}
              </span>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {selectedIds.size > 0 && (
            <>
              <Button
                size="sm"
                className="bg-green-500/15 text-green-400 border border-green-500/30 hover:bg-green-500/25 h-8"
                onClick={() => setConfirmAction({ type: 'bulk-approve' })}
              >
                <ShieldCheck className="w-4 h-4 mr-1" />
                Одобрить ({selectedIds.size})
              </Button>
              <Button
                size="sm"
                className="bg-red-500/15 text-red-400 border border-red-500/30 hover:bg-red-500/25 h-8"
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
            className="border-[#2d3a54] text-[#8899aa] hover:text-foreground h-8"
            onClick={() => fetchNews()}
            disabled={loading}
          >
            <RefreshCw className={cn('w-4 h-4 mr-2', loading && 'animate-spin')} />
            Обновить
          </Button>
        </div>
      </div>

      {/* Loading */}
      {loading ? (
        <div className="space-y-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <Card key={i} className="bg-[#1e2a4a] border-[#2d3a54]">
              <CardContent className="p-5">
                <div className="flex gap-3">
                  <Skeleton className="w-5 h-5 bg-[#2a3555] mt-0.5" />
                  <div className="flex-1">
                    <Skeleton className="h-4 w-64 bg-[#2a3555] mb-3" />
                    <Skeleton className="h-3 w-full bg-[#2a3555] mb-2" />
                    <Skeleton className="h-3 w-3/4 bg-[#2a3555]" />
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : news.length === 0 ? (
        <Card className="bg-[#1e2a4a] border-[#2d3a54]">
          <CardContent className="p-16 text-center">
            <ShieldCheck className="w-14 h-14 text-[#2d3a54] mx-auto mb-4" />
            <p className="text-[#8899aa] text-lg font-medium">Нет новостей для модерации</p>
            <p className="text-[#6c7b8f] text-sm mt-1">Все новости обработаны</p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {/* Select all */}
          <div className="flex items-center gap-2 px-1">
            <Checkbox
              checked={selectedIds.size === news.length && news.length > 0}
              onCheckedChange={toggleSelectAll}
              className="border-[#2d3a54]"
            />
            <span className="text-xs text-[#6c7b8f]">Выбрать все ({news.length})</span>
          </div>

          {/* News cards */}
          {news.map((item) => (
            <NewsCard
              key={item.id}
              item={item}
              selected={selectedIds.has(item.id)}
              onToggleSelect={() => toggleSelect(item.id)}
              onApprove={() => handleAction(item.id, 'approve')}
              onReject={() => handleAction(item.id, 'reject')}
              onEdit={(formatted_post: string) => handleEdit(item.id, formatted_post, (() => {
                try { return JSON.parse(item.images || '[]') } catch { return [] }
              })())}
              onEditImages={(images: string[]) => {
                const text = item.formatted_post || item.ai_summary || item.original_text
                handleEdit(item.id, text, images)
              }}
            />
          ))}
        </div>
      )}

      {/* Bulk action confirmation */}
      <AlertDialog open={!!confirmAction} onOpenChange={() => setConfirmAction(null)}>
        <AlertDialogContent className="bg-[#1e2a4a] border-[#2d3a54]">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-foreground">
              {confirmAction?.type === 'bulk-approve' ? 'Массовое одобрение' : 'Массовое отклонение'}
            </AlertDialogTitle>
            <AlertDialogDescription className="text-[#8899aa]">
              Вы уверены, что хотите {confirmAction?.type === 'bulk-approve' ? 'одобрить' : 'отклонить'}{' '}
              {selectedIds.size} новостей?
              Это действие нельзя отменить.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="border-[#2d3a54] text-[#8899aa] hover:text-foreground">Отмена</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (confirmAction) handleBulkAction(confirmAction.type === 'bulk-approve' ? 'approve' : 'reject')
              }}
              className={
                confirmAction?.type === 'bulk-approve'
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
