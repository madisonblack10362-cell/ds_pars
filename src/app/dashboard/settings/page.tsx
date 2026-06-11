'use client'

import { useState, useEffect } from 'react'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Checkbox } from '@/components/ui/checkbox'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import { Settings, Loader2, Brain, Clock, FileText, Zap } from 'lucide-react'
import { useToast } from '@/hooks/use-toast'

interface SettingsData {
  ai_model: string
  default_priority_threshold: string
  min_message_length: number
  auto_publish_high: boolean
  auto_publish_medium: boolean
  auto_publish_low: boolean
  check_interval: number
}

export default function SettingsPage() {
  const [settings, setSettings] = useState<SettingsData>({
    ai_model: 'meta/llama-3.1-8b-instruct',
    default_priority_threshold: 'medium',
    min_message_length: 50,
    auto_publish_high: false,
    auto_publish_medium: false,
    auto_publish_low: false,
    check_interval: 300,
  })
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const { toast } = useToast()

  useEffect(() => {
    const fetchSettings = async () => {
      try {
        const res = await fetch('/api/settings')
        if (res.ok) {
          const data = await res.json()
          setSettings(data)
        }
      } catch (err) {
        console.error('Failed to fetch settings:', err)
      } finally {
        setLoading(false)
      }
    }
    fetchSettings()
  }, [])

  const handleSave = async () => {
    setSaving(true)
    try {
      const res = await fetch('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings),
      })
      if (res.ok) {
        toast({ title: 'Сохранено', description: 'Настройки успешно обновлены' })
      } else {
        const data = await res.json()
        toast({ title: 'Ошибка', description: data.error || 'Не удалось сохранить', variant: 'destructive' })
      }
    } catch {
      toast({ title: 'Ошибка', description: 'Не удалось сохранить настройки', variant: 'destructive' })
    } finally {
      setSaving(false)
    }
  }

  const updateSetting = <K extends keyof SettingsData>(key: K, value: SettingsData[K]) => {
    setSettings((prev) => ({ ...prev, [key]: value }))
  }

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-48 bg-secondary" />
        <Skeleton className="h-64 bg-secondary rounded-xl" />
        <Skeleton className="h-48 bg-secondary rounded-xl" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Настройки</h1>
          <p className="text-muted-foreground text-sm mt-1">Конфигурация мониторинга и AI-анализа</p>
        </div>
        <Button
          className="bg-[#58a6ff] hover:bg-[#4a96ef] text-primary-foreground"
          onClick={handleSave}
          disabled={saving}
        >
          {saving ? (
            <>
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              Сохранение...
            </>
          ) : (
            'Сохранить настройки'
          )}
        </Button>
      </div>

      {/* AI Settings */}
      <Card className="bg-card border-border">
        <CardHeader>
          <div className="flex items-center gap-2">
            <Brain className="w-4 h-4 text-[#58a6ff]" />
            <CardTitle className="text-foreground text-base">Настройки AI</CardTitle>
          </div>
          <CardDescription>Параметры для анализа новостей с помощью искусственного интеллекта</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* AI Model */}
          <div className="space-y-2">
            <Label htmlFor="ai_model" className="text-foreground">Модель AI</Label>
            <Select
              value={settings.ai_model}
              onValueChange={(v) => updateSetting('ai_model', v)}
            >
              <SelectTrigger className="w-full sm:w-80 bg-secondary border-border text-foreground">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="meta/llama-3.1-8b-instruct">Llama 3.1 8B (NVIDIA NIM)</SelectItem>
                <SelectItem value="meta/llama-3.1-70b-instruct">Llama 3.1 70B (NVIDIA NIM)</SelectItem>
                <SelectItem value="gpt-4o">GPT-4o</SelectItem>
                <SelectItem value="gpt-4o-mini">GPT-4o Mini</SelectItem>
                <SelectItem value="claude-3-5-sonnet">Claude 3.5 Sonnet</SelectItem>
                <SelectItem value="custom">Другая (укажите ниже)</SelectItem>
              </SelectContent>
            </Select>
            {settings.ai_model === 'custom' && (
              <Input
                value={settings.ai_model === 'custom' ? '' : settings.ai_model}
                onChange={(e) => updateSetting('ai_model', e.target.value)}
                placeholder="Введите название модели"
                className="mt-2 bg-secondary border-border text-foreground placeholder:text-muted-foreground"
              />
            )}
          </div>

          <Separator className="bg-border" />

          {/* Priority threshold */}
          <div className="space-y-2">
            <Label htmlFor="priority_threshold" className="text-foreground">Порог приоритета по умолчанию</Label>
            <Select
              value={settings.default_priority_threshold}
              onValueChange={(v) => updateSetting('default_priority_threshold', v)}
            >
              <SelectTrigger className="w-full sm:w-80 bg-secondary border-border text-foreground">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="high">Высокий</SelectItem>
                <SelectItem value="medium">Средний</SelectItem>
                <SelectItem value="low">Низкий</SelectItem>
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              Минимальный приоритет новостей для публикации
            </p>
          </div>

          <Separator className="bg-border" />

          {/* Min message length */}
          <div className="space-y-2">
            <Label htmlFor="min_length" className="text-foreground">Минимальная длина сообщения</Label>
            <Input
              id="min_length"
              type="number"
              value={settings.min_message_length}
              onChange={(e) => updateSetting('min_message_length', Number(e.target.value))}
              className="w-full sm:w-80 bg-secondary border-border text-foreground"
              min={10}
              max={5000}
            />
            <p className="text-xs text-muted-foreground">
              Сообщения короче этого значения будут игнорироваться
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Auto-publish settings */}
      <Card className="bg-card border-border">
        <CardHeader>
          <div className="flex items-center gap-2">
            <Zap className="w-4 h-4 text-[#58a6ff]" />
            <CardTitle className="text-foreground text-base">Авто-публикация</CardTitle>
          </div>
          <CardDescription>Настройки автоматической публикации новостей по приоритету</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-4">
            <div className="flex items-start gap-3 p-3 rounded-lg bg-secondary/50">
              <Checkbox
                id="auto_high"
                checked={settings.auto_publish_high}
                onCheckedChange={(v) => updateSetting('auto_publish_high', !!v)}
                className="border-border mt-0.5"
              />
              <div className="flex-1">
                <Label htmlFor="auto_high" className="text-foreground cursor-pointer">
                  Авто-публикация: Высокий приоритет
                </Label>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Новости с высоким приоритетом будут опубликованы автоматически без модерации
                </p>
              </div>
            </div>

            <div className="flex items-start gap-3 p-3 rounded-lg bg-secondary/50">
              <Checkbox
                id="auto_medium"
                checked={settings.auto_publish_medium}
                onCheckedChange={(v) => updateSetting('auto_publish_medium', !!v)}
                className="border-border mt-0.5"
              />
              <div className="flex-1">
                <Label htmlFor="auto_medium" className="text-foreground cursor-pointer">
                  Авто-публикация: Средний приоритет
                </Label>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Новости со средним приоритетом будут опубликованы автоматически
                </p>
              </div>
            </div>

            <div className="flex items-start gap-3 p-3 rounded-lg bg-secondary/50">
              <Checkbox
                id="auto_low"
                checked={settings.auto_publish_low}
                onCheckedChange={(v) => updateSetting('auto_publish_low', !!v)}
                className="border-border mt-0.5"
              />
              <div className="flex-1">
                <Label htmlFor="auto_low" className="text-foreground cursor-pointer">
                  Авто-публикация: Низкий приоритет
                </Label>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Новости с низким приоритетом будут опубликованы автоматически
                </p>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Check interval */}
      <Card className="bg-card border-border">
        <CardHeader>
          <div className="flex items-center gap-2">
            <Clock className="w-4 h-4 text-[#58a6ff]" />
            <CardTitle className="text-foreground text-base">Интервал проверки</CardTitle>
          </div>
          <CardDescription>Частота проверки источников на новые сообщения</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="interval" className="text-foreground">Интервал (секунды)</Label>
            <Select
              value={String(settings.check_interval)}
              onValueChange={(v) => updateSetting('check_interval', Number(v))}
            >
              <SelectTrigger className="w-full sm:w-80 bg-secondary border-border text-foreground">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="60">1 минута</SelectItem>
                <SelectItem value="120">2 минуты</SelectItem>
                <SelectItem value="300">5 минут</SelectItem>
                <SelectItem value="600">10 минут</SelectItem>
                <SelectItem value="900">15 минут</SelectItem>
                <SelectItem value="1800">30 минут</SelectItem>
                <SelectItem value="3600">1 час</SelectItem>
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              Как часто бот проверяет источники на наличие новых сообщений
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
