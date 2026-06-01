'use client'

import { useState, useEffect, useCallback } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Skeleton } from '@/components/ui/skeleton'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
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
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  Plus,
  RefreshCw,
  Trash2,
  Edit2,
  Power,
  PowerOff,
  MessageSquare,
  Send,
  Globe,
} from 'lucide-react'
import { useToast } from '@/hooks/use-toast'

interface Source {
  id: number
  name: string
  type: string
  enabled: boolean
  config: Record<string, string>
  created_at: string
  last_check: string | null
  news_count: number
}

function SourceTypeIcon({ type }: { type: string }) {
  switch (type) {
    case 'discord': return <MessageSquare className="w-4 h-4 text-indigo-400" />
    case 'telegram': return <Send className="w-4 h-4 text-sky-400" />
    case 'vk': return <MessageSquare className="w-4 h-4 text-blue-400" />
    case 'website': return <Globe className="w-4 h-4 text-teal-400" />
    default: return <Globe className="w-4 h-4 text-muted-foreground" />
  }
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

const sourceTypeFields: Record<string, { key: string; label: string; placeholder: string }[]> = {
  discord: [
    { key: 'guild_id', label: 'ID сервера', placeholder: '1234567890' },
    { key: 'channel_id', label: 'ID канала', placeholder: '1234567890' },
  ],
  telegram: [
    { key: 'channel_username', label: 'Имя канала', placeholder: '@dayz_updates' },
  ],
  vk: [
    { key: 'group_id', label: 'ID группы', placeholder: '-12345678' },
  ],
  website: [
    { key: 'url', label: 'URL', placeholder: 'https://dayz.com/news' },
    { key: 'css_selector', label: 'CSS селектор', placeholder: '.news-item' },
  ],
}

export default function SourcesPage() {
  const [sources, setSources] = useState<Source[]>([])
  const [loading, setLoading] = useState(true)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [deleteConfirm, setDeleteConfirm] = useState<number | null>(null)
  const [editingSource, setEditingSource] = useState<Source | null>(null)
  const [formType, setFormType] = useState('discord')
  const [formName, setFormName] = useState('')
  const [formConfig, setFormConfig] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const { toast } = useToast()

  const fetchSources = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch('/api/sources')
      if (res.ok) {
        const data = await res.json()
        setSources(data.sources || data || [])
      }
    } catch (err) {
      console.error('Failed to fetch sources:', err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchSources()
  }, [fetchSources])

  const openAddDialog = () => {
    setEditingSource(null)
    setFormName('')
    setFormType('discord')
    setFormConfig({})
    setDialogOpen(true)
  }

  const openEditDialog = (source: Source) => {
    setEditingSource(source)
    setFormName(source.name)
    setFormType(source.type)
    setFormConfig({ ...source.config })
    setDialogOpen(true)
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      const body = {
        name: formName,
        type: formType,
        config: formConfig,
      }
      const url = editingSource ? `/api/sources?id=${editingSource.id}` : '/api/sources'
      const method = editingSource ? 'PUT' : 'POST'

      const res = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })

      if (res.ok) {
        toast({
          title: editingSource ? 'Источник обновлён' : 'Источник добавлен',
          description: `${formName} успешно ${editingSource ? 'обновлён' : 'добавлен'}`,
        })
        setDialogOpen(false)
        fetchSources()
      } else {
        const data = await res.json()
        toast({ title: 'Ошибка', description: data.error || 'Не удалось сохранить', variant: 'destructive' })
      }
    } catch {
      toast({ title: 'Ошибка', description: 'Не удалось сохранить', variant: 'destructive' })
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (id: number) => {
    try {
      const res = await fetch(`/api/sources?id=${id}`, { method: 'DELETE' })
      if (res.ok) {
        toast({ title: 'Удалено', description: 'Источник удалён' })
        fetchSources()
      }
    } catch {
      toast({ title: 'Ошибка', description: 'Не удалось удалить', variant: 'destructive' })
    }
    setDeleteConfirm(null)
  }

  const handleToggle = async (source: Source) => {
    try {
      const res = await fetch(`/api/sources`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: source.id, enabled: !source.enabled }),
      })
      if (res.ok) {
        fetchSources()
      }
    } catch {
      toast({ title: 'Ошибка', description: 'Не удалось изменить статус', variant: 'destructive' })
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Источники</h1>
          <p className="text-muted-foreground text-sm mt-1">Управление источниками новостей</p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            onClick={openAddDialog}
            className="bg-[#58a6ff] hover:bg-[#4a96ef] text-primary-foreground"
          >
            <Plus className="w-4 h-4 mr-2" />
            Добавить
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="border-border text-muted-foreground hover:text-foreground"
            onClick={fetchSources}
            disabled={loading}
          >
            <RefreshCw className={`w-4 h-4 mr-2 ${loading ? 'animate-spin' : ''}`} />
            Обновить
          </Button>
        </div>
      </div>

      {/* Sources table */}
      <Card className="bg-card border-border">
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow className="border-border hover:bg-transparent">
                <TableHead className="text-muted-foreground">Название</TableHead>
                <TableHead className="text-muted-foreground">Тип</TableHead>
                <TableHead className="text-muted-foreground hidden md:table-cell">Конфигурация</TableHead>
                <TableHead className="text-muted-foreground hidden lg:table-cell">Новости</TableHead>
                <TableHead className="text-muted-foreground hidden lg:table-cell">Последняя проверка</TableHead>
                <TableHead className="text-muted-foreground">Статус</TableHead>
                <TableHead className="text-muted-foreground">Действия</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                Array.from({ length: 4 }).map((_, i) => (
                  <TableRow key={i} className="border-border">
                    <TableCell><Skeleton className="h-4 w-32 bg-secondary" /></TableCell>
                    <TableCell><Skeleton className="h-5 w-20 bg-secondary" /></TableCell>
                    <TableCell className="hidden md:table-cell"><Skeleton className="h-4 w-40 bg-secondary" /></TableCell>
                    <TableCell className="hidden lg:table-cell"><Skeleton className="h-4 w-8 bg-secondary" /></TableCell>
                    <TableCell className="hidden lg:table-cell"><Skeleton className="h-4 w-24 bg-secondary" /></TableCell>
                    <TableCell><Skeleton className="h-5 w-10 bg-secondary" /></TableCell>
                    <TableCell><Skeleton className="h-4 w-20 bg-secondary" /></TableCell>
                  </TableRow>
                ))
              ) : sources.length === 0 ? (
                <TableRow className="border-border">
                  <TableCell colSpan={7} className="text-center py-12 text-muted-foreground">
                    Нет источников. Нажмите &quot;Добавить&quot; для создания.
                  </TableCell>
                </TableRow>
              ) : (
                sources.map((source) => (
                  <TableRow key={source.id} className="border-border">
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <SourceTypeIcon type={source.type} />
                        <span className="text-sm text-foreground font-medium">{source.name}</span>
                      </div>
                    </TableCell>
                    <TableCell>
                      <SourceTypeBadge type={source.type} />
                    </TableCell>
                    <TableCell className="hidden md:table-cell">
                      <div className="text-xs text-muted-foreground space-y-0.5">
                        {Object.entries(source.config).map(([k, v]) => (
                          <div key={k}>
                            <span className="text-muted-foreground/70">{k}:</span> {v}
                          </div>
                        ))}
                      </div>
                    </TableCell>
                    <TableCell className="hidden lg:table-cell text-sm text-foreground">
                      {source.news_count}
                    </TableCell>
                    <TableCell className="hidden lg:table-cell text-xs text-muted-foreground">
                      {source.last_check
                        ? new Date(source.last_check).toLocaleString('ru-RU')
                        : '—'
                      }
                    </TableCell>
                    <TableCell>
                      <Switch
                        checked={source.enabled}
                        onCheckedChange={() => handleToggle(source)}
                      />
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1">
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8 text-muted-foreground hover:text-foreground"
                          onClick={() => openEditDialog(source)}
                        >
                          <Edit2 className="w-3.5 h-3.5" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8 text-muted-foreground hover:text-destructive"
                          onClick={() => setDeleteConfirm(source.id)}
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Add/Edit dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="bg-card border-border max-w-lg">
          <DialogHeader>
            <DialogTitle className="text-foreground">
              {editingSource ? 'Редактирование источника' : 'Добавление источника'}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label className="text-foreground">Название</Label>
              <Input
                value={formName}
                onChange={(e) => setFormName(e.target.value)}
                placeholder="Например: Официальный Discord"
                className="bg-secondary border-border text-foreground placeholder:text-muted-foreground"
              />
            </div>
            <div className="space-y-2">
              <Label className="text-foreground">Тип источника</Label>
              <Select value={formType} onValueChange={(v) => { setFormType(v); setFormConfig({}) }}>
                <SelectTrigger className="w-full bg-secondary border-border text-foreground">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="discord">Discord</SelectItem>
                  <SelectItem value="telegram">Telegram</SelectItem>
                  <SelectItem value="vk">VK</SelectItem>
                  <SelectItem value="website">Сайт</SelectItem>
                </SelectContent>
              </Select>
            </div>
            {/* Dynamic fields */}
            {(sourceTypeFields[formType] || []).map((field) => (
              <div key={field.key} className="space-y-2">
                <Label className="text-foreground">{field.label}</Label>
                <Input
                  value={formConfig[field.key] || ''}
                  onChange={(e) => setFormConfig((prev) => ({ ...prev, [field.key]: e.target.value }))}
                  placeholder={field.placeholder}
                  className="bg-secondary border-border text-foreground placeholder:text-muted-foreground"
                />
              </div>
            ))}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              className="border-border text-muted-foreground hover:text-foreground"
              onClick={() => setDialogOpen(false)}
            >
              Отмена
            </Button>
            <Button
              className="bg-[#58a6ff] hover:bg-[#4a96ef] text-primary-foreground"
              onClick={handleSave}
              disabled={saving || !formName}
            >
              {saving ? 'Сохранение...' : editingSource ? 'Сохранить' : 'Добавить'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete confirmation */}
      <AlertDialog open={!!deleteConfirm} onOpenChange={() => setDeleteConfirm(null)}>
        <AlertDialogContent className="bg-card border-border">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-foreground">Удаление источника</AlertDialogTitle>
            <AlertDialogDescription className="text-muted-foreground">
              Вы уверены, что хотите удалить этот источник? Это действие нельзя отменить.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="border-border text-muted-foreground hover:text-foreground">Отмена</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => deleteConfirm && handleDelete(deleteConfirm)}
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
