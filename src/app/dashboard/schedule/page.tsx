'use client'

import { sanitizeTelegramHtml } from '@/lib/sanitize'
import { useState, useEffect, useMemo, useRef } from 'react'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, DialogTrigger } from '@/components/ui/dialog'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog'
import { Clock, Loader2, Save, CalendarClock, CheckCircle2, MinusCircle, Timer, Zap, TrendingUp, Inbox, MessageSquare, Plus, Trash2, SkipForward, ChevronLeft, ChevronRight, Pencil, CheckCircle, ImageIcon, Video, X, Upload, Eye, EyeOff } from 'lucide-react'
import { useToast } from '@/hooks/use-toast'

interface QueueItem {
  id: string
  title: string
  priority: string
  newsType: string
  formattedPost: string
  content: string
  images: string
  serverName: string
  scheduledAt?: string
}

interface SlotInfo {
  slot: number
  key: string
  time: string
  queueCount: number
  status: 'waiting' | 'published' | 'empty' | 'skipped'
  queue: QueueItem[]
}

interface ScheduleData {
  date: string
  isToday: boolean
  slots: SlotInfo[]
  totalItems: number
}

// ─── Media Gallery Component (from moderation page) ───
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
          <div className="flex gap-2">
            <Input
              value={newUrl}
              onChange={(e) => setNewUrl(e.target.value)}
              placeholder="URL изображения или видео..."
              className="bg-secondary border-border text-foreground text-sm h-8"
              onKeyDown={(e) => e.key === 'Enter' && handleAddUrl()}
            />
            <Button
              size="sm"
              variant="outline"
              className="border-border text-muted-foreground hover:text-foreground h-8 px-3"
              onClick={handleAddUrl}
              disabled={!newUrl.trim()}
            >
              <Plus className="w-3.5 h-3.5" />
            </Button>
          </div>
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
              className="border-border text-muted-foreground hover:text-foreground h-8"
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

const ACCENT = '#58a6ff'
const ACCENT_DARK = '#3a8ae0'

const SLOT_COLORS = [
  '#58a6ff', '#8b5cf6', '#06b6d4', '#10b981',
  '#f59e0b', '#ef4444', '#ec4899', '#6366f1',
  '#14b8a6', '#f97316', '#84cc16', '#a855f7',
  '#0ea5e9', '#22c55e', '#eab308', '#d946ef',
  '#fb923c', '#38bdf8', '#4ade80', '#f472b6',
]

// ─── Telegram HTML → rich HTML ───
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

// ─── Mini Telegram Preview for schedule cards (FIXED: images don't stretch) ───
function MiniTelegramPreview({ item }: { item: QueueItem }) {
  const previewText = item.formattedPost || item.content || item.title || 'Без текста'
  const richHtml = telegramHtmlToRich(previewText)

  let images: string[] = []
  try { images = JSON.parse(item.images) } catch { images = [] }
  const displayImage = images[0] || null

  return (
    <div className="rounded-xl overflow-hidden border border-[#2d3a54]/80 shadow-md shadow-black/20 w-full" style={{minWidth:0}}>
      {/* Channel header */}
      <div className="bg-[#2b5278] px-3 py-1.5 flex items-center gap-2" style={{minWidth:0}}>
        <div className="w-5 h-5 rounded-full bg-[#58a6ff]/20 flex items-center justify-center border border-[#58a6ff]/30">
          <MessageSquare className="w-2.5 h-2.5 text-[#58a6ff]" />
        </div>
        <span className="text-[11px] font-semibold text-white/90">DayZ Monitor</span>
        <span className="text-[10px] text-white/40">канал</span>
      </div>

      {/* Message area — fixed height with scroll */}
      <div className="bg-[#0e1621] px-3 pb-2.5 pt-1 max-h-[180px] overflow-y-auto" style={{minWidth:0,overflowX:'hidden'}}>
        {displayImage && (
          <div className="mb-1.5 overflow-hidden rounded-md bg-[#1a2733]">
            <img
              src={displayImage}
              alt=""
              className="block w-full h-auto object-cover"
              style={{maxHeight:100,maxWidth:'100%'}}
              loading="lazy"
              referrerPolicy="no-referrer"
              onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }}
            />
          </div>
        )}
        <div className="bg-[#182533] rounded-xl rounded-tl-sm px-2.5 py-2 break-words" style={{maxWidth:'100%',overflowWrap:'break-word',wordBreak:'break-word'}}>
          <div
            className="text-[13px] text-[#f5f5f5] leading-[1.45] schedule-tg-content"
            style={{overflowWrap:'break-word',wordBreak:'break-word'}}
            dangerouslySetInnerHTML={{ __html: richHtml }}
          />
        </div>
      </div>
    </div>
  )
}

// ─── Priority dot ───
function PriorityDot({ priority }: { priority: string }) {
  const config: Record<string, { color: string; label: string }> = {
    high: { color: '#ef4444', label: 'HIGH' },
    medium: { color: '#f59e0b', label: 'MED' },
    low: { color: '#71717a', label: 'LOW' },
  }
  const c = config[priority] || config.low
  return (
    <div className="flex items-center gap-1.5">
      <div
        className="w-2 h-2 rounded-full"
        style={{ backgroundColor: c.color, boxShadow: priority !== 'low' ? `0 0 6px ${c.color}66` : 'none' }}
      />
      <span className="text-[10px] font-bold uppercase tracking-wider" style={{ color: c.color }}>
        {c.label}
      </span>
    </div>
  )
}

// ─── News type label ───
function NewsTypeLabel({ type }: { type: string }) {
  const labels: Record<string, string> = {
    wipe: 'Вайп',
    update: 'Обновление',
    event: 'Событие',
    maintenance: 'Тех. работы',
    patch: 'Патч',
    other: 'Другое',
  }
  return <span className="text-[10px] text-muted-foreground">{labels[type] || type || '—'}</span>
}

// ─── Generate 7 days (today + 6 days) ───
function getWeekDays(): { date: string; label: string; shortLabel: string; isToday: boolean }[] {
  const days: { date: string; label: string; shortLabel: string; isToday: boolean }[] = []
  const dayNames = ['Вс', 'Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб']
  const now = new Date()

  for (let i = 0; i < 7; i++) {
    const d = new Date(now)
    d.setDate(d.getDate() + i)

    const yyyy = d.getFullYear()
    const mm = String(d.getMonth() + 1).padStart(2, '0')
    const dd = String(d.getDate()).padStart(2, '0')
    const dateStr = `${yyyy}-${mm}-${dd}`

    const dayName = dayNames[d.getDay()]
    const monthNames = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']

    if (i === 0) {
      days.push({ date: dateStr, label: 'Сегодня', shortLabel: 'Сегодня', isToday: true })
    } else if (i === 1) {
      days.push({ date: dateStr, label: 'Завтра', shortLabel: 'Завтра', isToday: false })
    } else {
      days.push({
        date: dateStr,
        label: `${dayName}, ${d.getDate()} ${monthNames[d.getMonth()]}`,
        shortLabel: `${dayName}`,
        isToday: false,
      })
    }
  }
  return days
}

export default function SchedulePage() {
  const [schedule, setSchedule] = useState<ScheduleData | null>(null)
  const [editTimes, setEditTimes] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [editDialogOpen, setEditDialogOpen] = useState(false)
  const [addDialogOpen, setAddDialogOpen] = useState(false)
  const [newSlotTime, setNewSlotTime] = useState('')
  const [addingSlot, setAddingSlot] = useState(false)
  const [deleteKey, setDeleteKey] = useState<string | null>(null)
  const [deletingSlot, setDeletingSlot] = useState(false)
  const [selectedDayIndex, setSelectedDayIndex] = useState(0)
  const [editItem, setEditItem] = useState<QueueItem | null>(null)
  const [editText, setEditText] = useState('')
  const [editImages, setEditImages] = useState<string[]>([])
  const [editMediaOpen, setEditMediaOpen] = useState(false)
  const [editSaving, setEditSaving] = useState(false)
  const { toast } = useToast()

  const weekDays = useMemo(() => getWeekDays(), [])

  const fetchSchedule = async (signal?: AbortSignal) => {
    setLoading(true)
    try {
      const dateStr = weekDays[selectedDayIndex].date
      const res = await fetch(`/api/schedule?date=${dateStr}&_t=${Date.now()}`, { signal })
      if (res.ok) {
        const data = await res.json()
        setSchedule(data)
        const times: Record<string, string> = {}
        for (const slot of data.slots) {
          times[slot.key] = slot.time
        }
        setEditTimes(times)
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return
      console.error('Failed to fetch schedule:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    const controller = new AbortController()
    fetchSchedule(controller.signal)
    return () => controller.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedDayIndex])

  const handleDayChange = (index: number) => {
    setSelectedDayIndex(index)
  }

  const handlePrevDay = () => {
    if (selectedDayIndex > 0) setSelectedDayIndex(selectedDayIndex - 1)
  }

  const handleNextDay = () => {
    if (selectedDayIndex < weekDays.length - 1) setSelectedDayIndex(selectedDayIndex + 1)
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      const res = await fetch('/api/schedule', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(editTimes),
      })
      if (res.ok) {
        toast({ title: 'Сохранено', description: 'Расписание успешно обновлено' })
        setEditDialogOpen(false)
        fetchSchedule()
      } else {
        const data = await res.json()
        toast({ title: 'Ошибка', description: data.error || 'Не удалось сохранить', variant: 'destructive' })
      }
    } catch {
      toast({ title: 'Ошибка', description: 'Не удалось сохранить расписание', variant: 'destructive' })
    } finally {
      setSaving(false)
    }
  }

  const handleAddSlot = async () => {
    if (!newSlotTime) return
    setAddingSlot(true)
    try {
      const res = await fetch('/api/schedule', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ time: newSlotTime }),
      })
      if (res.ok) {
        toast({ title: 'Слот добавлен', description: `Новый слот ${newSlotTime} создан` })
        setAddDialogOpen(false)
        setNewSlotTime('')
        fetchSchedule()
      } else {
        const data = await res.json()
        toast({ title: 'Ошибка', description: data.error || 'Не удалось добавить слот', variant: 'destructive' })
      }
    } catch {
      toast({ title: 'Ошибка', description: 'Не удалось добавить слот', variant: 'destructive' })
    } finally {
      setAddingSlot(false)
    }
  }

  const handleDeleteSlot = async () => {
    if (!deleteKey) return
    setDeletingSlot(true)
    try {
      const res = await fetch('/api/schedule', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: deleteKey }),
      })
      if (res.ok) {
        const data = await res.json()
        toast({
          title: 'Слот удалён',
          description: data.rescheduled > 0
            ? `${data.rescheduled} новостей перенесено на другой слот`
            : 'Слот успешно удалён',
        })
        setDeleteKey(null)
        fetchSchedule()
      } else {
        const data = await res.json()
        toast({ title: 'Ошибка', description: data.error || 'Не удалось удалить слот', variant: 'destructive' })
      }
    } catch {
      toast({ title: 'Ошибка', description: 'Не удалось удалить слот', variant: 'destructive' })
    } finally {
      setDeletingSlot(false)
    }
  }

  const openEditDialog = (item: QueueItem) => {
    setEditItem(item)
    setEditText(item.formattedPost || item.content || item.title || '')
    try { setEditImages(JSON.parse(item.images || '[]')) } catch { setEditImages([]) }
    setEditMediaOpen(false)
  }

  const handleSaveEdit = async () => {
    if (!editItem) return
    setEditSaving(true)
    try {
      const res = await fetch('/api/publish-queue', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ news_id: editItem.id, formatted_post: editText, images: editImages }),
      })
      if (res.ok) {
        toast({ title: 'Сохранено', description: 'Новость обновлена' })
        setEditItem(null)
        fetchSchedule()
      } else {
        const data = await res.json()
        toast({ title: 'Ошибка', description: data.error || 'Не удалось сохранить', variant: 'destructive' })
      }
    } catch {
      toast({ title: 'Ошибка', description: 'Не удалось сохранить', variant: 'destructive' })
    } finally {
      setEditSaving(false)
    }
  }

  const getStatusBadge = (status: string, count: number) => {
    switch (status) {
      case 'waiting':
        return (
          <Badge className="gap-1.5 bg-amber-500/10 text-amber-400 border-amber-500/25 hover:bg-amber-500/15 px-2.5 py-0.5 font-medium">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-amber-400" />
            </span>
            Ожидание ({count})
          </Badge>
        )
      case 'published':
        return (
          <Badge className="gap-1.5 bg-emerald-500/10 text-emerald-400 border-emerald-500/25 hover:bg-emerald-500/15 px-2.5 py-0.5 font-medium">
            <CheckCircle2 className="w-3.5 h-3.5" />
            Опубликовано
          </Badge>
        )
      case 'empty':
        return (
          <Badge className="gap-1.5 bg-[#58a6ff]/8 text-[#79c0ff] border-[#58a6ff]/20 hover:bg-[#58a6ff]/12 px-2.5 py-0.5 font-medium">
            <span className="inline-flex rounded-full h-2 w-2 bg-[#58a6ff]/60" />
            Пусто
          </Badge>
        )
      case 'skipped':
        return (
          <Badge className="gap-1.5 bg-violet-500/10 text-violet-400 border-violet-500/25 hover:bg-violet-500/15 px-2.5 py-0.5 font-medium">
            <SkipForward className="w-3.5 h-3.5" />
            Без публикаций
          </Badge>
        )
      default:
        return null
    }
  }

  const getSlotColor = (index: number) => SLOT_COLORS[index % SLOT_COLORS.length]

  const getSlotBg = (index: number) => {
    const hex = SLOT_COLORS[index % SLOT_COLORS.length]
    const r = parseInt(hex.slice(1, 3), 16)
    const g = parseInt(hex.slice(3, 5), 16)
    const b = parseInt(hex.slice(5, 7), 16)
    return `rgba(${r}, ${g}, ${b}, 0.08)`
  }

  const currentDay = weekDays[selectedDayIndex]

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div className="space-y-1">
          <div className="flex items-center gap-3">
            <div
              className="w-10 h-10 rounded-xl flex items-center justify-center"
              style={{ background: `linear-gradient(135deg, ${ACCENT}20, ${ACCENT}05)` }}
            >
              <CalendarClock className="w-5 h-5" style={{ color: ACCENT }} />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-foreground tracking-tight">Расписание публикаций</h1>
              <p className="text-muted-foreground text-sm">Управление слотами автопубликации по дням</p>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Dialog open={addDialogOpen} onOpenChange={setAddDialogOpen}>
            <DialogTrigger asChild>
              <Button variant="outline" className="gap-2 border-[#2d3a54] text-[#8899aa] hover:text-foreground hover:border-[#58a6ff]/40">
                <Plus className="w-4 h-4" />
                Добавить слот
              </Button>
            </DialogTrigger>
            <DialogContent className="bg-card border-border">
              <DialogHeader>
                <DialogTitle className="text-foreground">Новый слот</DialogTitle>
                <DialogDescription className="text-muted-foreground">
                  Укажите время для нового слота публикации
                </DialogDescription>
              </DialogHeader>
              <div className="py-4">
                <Label className="text-foreground mb-2 block">Время</Label>
                <Input
                  type="time"
                  value={newSlotTime}
                  onChange={(e) => setNewSlotTime(e.target.value)}
                  className="bg-secondary border-border text-foreground w-40"
                />
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => { setAddDialogOpen(false); setNewSlotTime('') }} className="border-border text-muted-foreground hover:text-foreground">
                  Отмена
                </Button>
                <Button
                  className="gap-2 text-primary-foreground font-medium"
                  style={{ background: `linear-gradient(135deg, ${ACCENT}, ${ACCENT_DARK})` }}
                  onClick={handleAddSlot}
                  disabled={addingSlot || !newSlotTime}
                >
                  {addingSlot ? <><Loader2 className="w-4 h-4 animate-spin" /> Добавление...</> : <><Plus className="w-4 h-4" /> Добавить</>}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>

          <Dialog open={editDialogOpen} onOpenChange={setEditDialogOpen}>
            <DialogTrigger asChild>
              <Button
                className="gap-2 text-primary-foreground font-medium shadow-lg shadow-[#58a6ff]/20 hover:shadow-[#58a6ff]/30 transition-all duration-200"
                style={{ background: `linear-gradient(135deg, ${ACCENT}, ${ACCENT_DARK})` }}
              >
                <Clock className="w-4 h-4" />
                Изменить расписание
              </Button>
            </DialogTrigger>
            <DialogContent className="bg-card border-border max-h-[80vh] overflow-y-auto">
              <DialogHeader>
                <DialogTitle className="text-foreground">Настройка слотов</DialogTitle>
                <DialogDescription className="text-muted-foreground">
                  Укажите время публикаций. Формат: ЧЧ:ММ
                </DialogDescription>
              </DialogHeader>
              <div className="space-y-4 py-4">
                {schedule?.slots.map((slot) => (
                  <div key={slot.key} className="flex items-center gap-4">
                    <Label className="text-foreground min-w-[80px]">Слот {slot.slot}</Label>
                    <Input
                      type="time"
                      value={editTimes[slot.key] || slot.time}
                      onChange={(e) => setEditTimes((prev) => ({ ...prev, [slot.key]: e.target.value }))}
                      className="bg-secondary border-border text-foreground w-32"
                    />
                  </div>
                ))}
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setEditDialogOpen(false)} className="border-border text-muted-foreground hover:text-foreground">
                  Отмена
                </Button>
                <Button
                  className="gap-2 text-primary-foreground font-medium"
                  style={{ background: `linear-gradient(135deg, ${ACCENT}, ${ACCENT_DARK})` }}
                  onClick={handleSave}
                  disabled={saving}
                >
                  {saving ? <><Loader2 className="w-4 h-4 animate-spin" /> Сохранение...</> : <><Save className="w-4 h-4" /> Сохранить</>}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </div>
      </div>

      {/* Week day selector */}
      <div className="flex items-center gap-1.5 overflow-x-auto pb-1 scrollbar-none" style={{maxWidth:'100%', WebkitOverflowScrolling:'touch'}}>
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8 shrink-0 text-muted-foreground hover:text-foreground"
          onClick={handlePrevDay}
          disabled={selectedDayIndex === 0}
        >
          <ChevronLeft className="w-4 h-4" />
        </Button>

        <div className="flex gap-1 flex-1 justify-center" style={{minWidth:0}}>
          {weekDays.map((day, index) => (
            <button
              key={day.date}
              onClick={() => handleDayChange(index)}
              className={`
                flex flex-col items-center px-2 py-1.5 rounded-lg text-xs font-medium transition-all shrink-0 min-w-[42px]
                ${selectedDayIndex === index
                  ? 'bg-[#58a6ff]/15 text-[#58a6ff] border border-[#58a6ff]/30 shadow-sm shadow-[#58a6ff]/10'
                  : 'text-muted-foreground hover:text-foreground hover:bg-secondary/50 border border-transparent'
                }
              `}
            >
              <span className={`text-[10px] uppercase tracking-wider ${selectedDayIndex === index ? 'text-[#58a6ff]/70' : ''}`}>
                {day.shortLabel}
              </span>
              <span className={`text-sm font-semibold mt-0.5 ${selectedDayIndex === index ? 'text-[#58a6ff]' : ''}`}>
                {new Date(day.date + 'T12:00:00').getDate()}
              </span>
              {selectedDayIndex === index && (
                <span className="w-1 h-1 rounded-full bg-[#58a6ff] mt-1" />
              )}
            </button>
          ))}
        </div>

        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8 shrink-0 text-muted-foreground hover:text-foreground"
          onClick={handleNextDay}
          disabled={selectedDayIndex === weekDays.length - 1}
        >
          <ChevronRight className="w-4 h-4" />
        </Button>
      </div>

      {/* Day header info */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-semibold text-foreground">{currentDay.label}</h2>
          <span className="text-xs text-muted-foreground">
            {new Date(currentDay.date + 'T12:00:00').toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' })}
          </span>
        </div>
        {!loading && schedule && (
          <div className="flex items-center gap-3">
            {schedule.totalItems > 0 && (
              <Badge className="gap-1.5 bg-[#58a6ff]/10 text-[#58a6ff] border-[#58a6ff]/25 px-2.5 py-0.5 font-medium">
                <Zap className="w-3 h-3" />
                {schedule.totalItems} {schedule.totalItems === 1 ? 'новость' : schedule.totalItems < 5 ? 'новости' : 'новостей'}
              </Badge>
            )}
            {schedule.isToday && (
              <Badge className="gap-1.5 bg-emerald-500/10 text-emerald-400 border-emerald-500/25 px-2.5 py-0.5 font-medium">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                Сегодня
              </Badge>
            )}
          </div>
        )}
      </div>

      {/* Slot cards */}
      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
          {Array.from({ length: 4 }).map((_, i) => (
            <Card key={i} className="bg-card border-border overflow-hidden">
              <div className="h-1 bg-secondary" />
              <CardHeader className="pb-3">
                <div className="flex items-center gap-3">
                  <Skeleton className="w-12 h-12 rounded-xl bg-secondary" />
                  <div className="flex-1 space-y-2">
                    <Skeleton className="h-4 w-40 bg-secondary" />
                    <Skeleton className="h-3 w-24 bg-secondary" />
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                <Skeleton className="h-32 bg-secondary rounded-xl" />
              </CardContent>
            </Card>
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 sm:gap-5" style={{minWidth:0}}>
          {schedule?.slots.map((slot, index) => {
            const isDashed = slot.status === 'empty' || slot.status === 'skipped'
            const cardClass = 'bg-card border-border overflow-hidden transition-all duration-300 hover:shadow-xl hover:-translate-y-0.5' + (isDashed ? ' border-dashed' : '')
            const barStyle = isDashed
              ? { background: 'repeating-linear-gradient(90deg, transparent, transparent 4px, rgba(113,113,122,0.3) 4px, rgba(113,113,122,0.3) 8px)' }
              : { background: `linear-gradient(90deg, ${getSlotColor(index)}, ${getSlotColor(index)}66, transparent)` }

            return (
              <Card key={slot.key} className={cardClass} style={{minWidth:0,overflow:'hidden'}}>
                <div className="h-1" style={barStyle} />

                <CardHeader className="pb-3">
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-center gap-3 min-w-0">
                      <div
                        className="relative w-14 h-14 rounded-2xl flex flex-col items-center justify-center shrink-0"
                        style={{
                          background: `linear-gradient(135deg, ${getSlotColor(index)}18, ${getSlotColor(index)}08)`,
                          border: `1px solid ${getSlotColor(index)}25`,
                        }}
                      >
                        <Clock
                          className="w-3.5 h-3.5 mb-0.5 opacity-50"
                          style={{ color: getSlotColor(index) }}
                        />
                        <span
                          className="text-[13px] font-bold tabular-nums leading-none"
                          style={{ color: getSlotColor(index) }}
                        >
                          {slot.time}
                        </span>
                      </div>

                      <div className="space-y-1">
                        <CardTitle className="text-foreground text-sm font-semibold">
                          Слот {slot.slot}
                        </CardTitle>
                        <CardDescription className="text-xs">
                          {slot.queueCount} в очереди
                        </CardDescription>
                      </div>
                    </div>

                    <div className="flex items-center gap-1.5 shrink-0">
                      {getStatusBadge(slot.status, slot.queueCount)}
                      {(schedule?.slots.length || 0) > 1 && (
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7 text-muted-foreground/40 hover:text-red-400 hover:bg-red-500/10 transition-colors"
                          onClick={() => setDeleteKey(slot.key)}
                          title="Удалить слот"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </Button>
                      )}
                    </div>
                  </div>
                </CardHeader>

                <CardContent>
                  {slot.queue.length === 0 ? (
                    <div
                      className="border-2 border-dashed border-border/50 rounded-xl flex flex-col items-center justify-center py-6"
                      style={{ background: `${getSlotColor(index)}04` }}
                    >
                      <div
                        className="w-10 h-10 rounded-xl flex items-center justify-center mb-2"
                        style={{ background: `${getSlotColor(index)}08` }}
                      >
                        <Inbox
                          className="w-5 h-5"
                          style={{ color: getSlotColor(index), opacity: 0.3 }}
                        />
                      </div>
                      <p className="text-xs text-muted-foreground/50 font-medium">
                        Нет запланированных новостей
                      </p>
                    </div>
                  ) : (
                    <div className="space-y-4">
                      {slot.queue.map((item, itemIndex) => (
                        <div key={item.id} className="space-y-2">
                          <div className="flex items-center gap-2 px-1">
                            <PriorityDot priority={item.priority} />
                            <span className="text-border">·</span>
                            <NewsTypeLabel type={item.newsType} />
                            {item.serverName && (
                              <>
                                <span className="text-border">·</span>
                                <span className="text-[11px] text-[#58a6ff] font-medium">{item.serverName}</span>
                              </>
                            )}
                            <div className="flex-1" />
                            <Badge
                              variant="outline"
                              className="border-amber-500/30 text-amber-400 text-[10px] shrink-0 font-medium"
                            >
                              <Zap className="w-2.5 h-2.5 mr-1" />
                              В очереди
                            </Badge>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-6 w-6 text-muted-foreground/50 hover:text-[#58a6ff] hover:bg-[#58a6ff]/10 transition-colors"
                              onClick={() => openEditDialog(item)}
                              title="Редактировать"
                            >
                              <Pencil className="w-3 h-3" />
                            </Button>
                          </div>
                          <MiniTelegramPreview item={item} />
                          {itemIndex < slot.queue.length - 1 && (
                            <div className="border-t border-border/30" />
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}

      {/* Edit dialog for scheduled items */}
      <Dialog open={!!editItem} onOpenChange={(open) => { if (!open) setEditItem(null) }}>
        <DialogContent className="bg-card border-border max-w-2xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="text-foreground">Редактирование новости</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <p className="text-[11px] text-[#58a6ff] font-medium mb-1.5 flex items-center gap-1">
                <Pencil className="w-3 h-3" />
                Текст поста
              </p>
              <Textarea
                value={editText}
                onChange={(e) => setEditText(e.target.value)}
                className="bg-secondary border-border text-foreground min-h-[160px] resize-y text-sm leading-relaxed"
                placeholder="Текст поста (поддерживается Telegram HTML)"
              />
            </div>
            <div>
              <button
                onClick={() => setEditMediaOpen(!editMediaOpen)}
                className="text-[11px] text-[#58a6ff] font-medium flex items-center gap-1"
              >
                <ImageIcon className="w-3 h-3" />
                Медиа ({editImages.length})
                {editMediaOpen ? <EyeOff className="w-3 h-3" /> : <Eye className="w-3 h-3" />}
              </button>
              {editMediaOpen && (
                <div className="mt-2">
                  <MediaGallery
                    images={editImages}
                    onRemove={(url) => setEditImages(prev => prev.filter(u => u !== url))}
                    onAdd={(url) => setEditImages(prev => [...prev, url])}
                    editable={true}
                  />
                </div>
              )}
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditItem(null)} className="border-border text-muted-foreground hover:text-foreground">
              Отмена
            </Button>
            <Button
              className="bg-[#58a6ff] hover:bg-[#4a96ef] text-primary-foreground"
              onClick={handleSaveEdit}
              disabled={editSaving}
            >
              {editSaving ? <><Loader2 className="w-4 h-4 animate-spin mr-1" /> Сохранение...</> : <><CheckCircle className="w-4 h-4 mr-1" /> Сохранить</>}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete confirmation dialog */}
      <AlertDialog open={!!deleteKey} onOpenChange={() => setDeleteKey(null)}>
        <AlertDialogContent className="bg-card border-border">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-foreground">Удалить слот?</AlertDialogTitle>
            <AlertDialogDescription className="text-muted-foreground">
              Слот будет удалён из расписания. Новости в очереди этого слота будут автоматически перенесены на ближайший следующий слот.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="border-border text-muted-foreground hover:text-foreground">
              Отмена
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDeleteSlot}
              disabled={deletingSlot}
              className="bg-red-500/15 text-red-400 hover:bg-red-500/25 border-0"
            >
              {deletingSlot ? (
                <><Loader2 className="w-4 h-4 animate-spin mr-1" /> Удаление...</>
              ) : (
                <><Trash2 className="w-4 h-4 mr-1" /> Удалить</>
              )}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
