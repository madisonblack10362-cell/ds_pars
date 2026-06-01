'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { useToast } from '@/hooks/use-toast'
import { Shield, Loader2 } from 'lucide-react'

// Check if running inside Telegram Web App
declare global {
  interface Window {
    Telegram?: {
      WebApp?: {
        initData: string
        ready: () => void
        expand: () => void
        close: () => void
        MainButton: {
          text: string
          show: () => void
          hide: () => void
        }
      }
    }
  }
}

export default function LoginPage() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [isTelegram, setIsTelegram] = useState(false)
  const router = useRouter()
  const { toast } = useToast()

  useEffect(() => {
    // Check if we're inside Telegram Web App
    const tg = window.Telegram?.WebApp
    if (tg && tg.initData) {
      setIsTelegram(true)
      tg.ready()
      tg.expand()

      // Auto-login with Telegram
      handleTelegramLogin(tg.initData)
    }

    // Check if already logged in
    const token = localStorage.getItem('auth_token')
    if (token) {
      router.replace('/dashboard')
    }
  }, [router])

  const handleTelegramLogin = async (initData: string) => {
    setIsLoading(true)
    try {
      const res = await fetch('/api/telegram-auth', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ initData }),
      })

      const data = await res.json()

      if (!res.ok) {
        throw new Error(data.error || 'Ошибка авторизации Telegram')
      }

      localStorage.setItem('auth_token', data.token)
      localStorage.setItem('auth_user', JSON.stringify(data.user))

      toast({
        title: 'Вход выполнен',
        description: `Добро пожаловать, ${data.user.username}!`,
      })

      router.push('/dashboard')
    } catch (err) {
      // If Telegram auth fails, show regular login
      setIsTelegram(false)
      toast({
        title: 'Ошибка Telegram авторизации',
        description: err instanceof Error ? err.message : 'Используйте логин/пароль',
        variant: 'destructive',
      })
    } finally {
      setIsLoading(false)
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setIsLoading(true)

    try {
      const res = await fetch('/api/auth', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      })

      const data = await res.json()

      if (!res.ok) {
        throw new Error(data.error || 'Ошибка авторизации')
      }

      localStorage.setItem('auth_token', data.token)
      localStorage.setItem('auth_user', JSON.stringify(data.user))

      toast({
        title: 'Успешный вход',
        description: `Добро пожаловать, ${data.user.username}!`,
      })

      router.push('/dashboard')
    } catch (err) {
      toast({
        title: 'Ошибка входа',
        description: err instanceof Error ? err.message : 'Неверный логин или пароль',
        variant: 'destructive',
      })
    } finally {
      setIsLoading(false)
    }
  }

  if (isTelegram && isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-background">
        <div className="flex flex-col items-center gap-3">
          <Shield className="w-12 h-12 text-[#58a6ff] animate-pulse" />
          <p className="text-muted-foreground">Авторизация через Telegram...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-4 bg-background">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-[#58a6ff]/10 mb-4">
            <Shield className="w-8 h-8 text-[#58a6ff]" />
          </div>
          <h1 className="text-2xl font-bold text-foreground">DayZ News Monitor</h1>
          <p className="text-muted-foreground mt-2">Панель администратора</p>
          {isTelegram && (
            <p className="text-xs text-[#58a6ff] mt-1">Telegram Mini App</p>
          )}
        </div>

        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="text-lg">Вход в систему</CardTitle>
            <CardDescription>Введите свои учетные данные для доступа</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="username">Имя пользователя</Label>
                <Input
                  id="username"
                  type="text"
                  placeholder="admin"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  required
                  className="bg-secondary border-border text-foreground placeholder:text-muted-foreground"
                  disabled={isLoading}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="password">Пароль</Label>
                <Input
                  id="password"
                  type="password"
                  placeholder="admin123"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  className="bg-secondary border-border text-foreground placeholder:text-muted-foreground"
                  disabled={isLoading}
                />
              </div>
              <Button
                type="submit"
                className="w-full bg-[#58a6ff] hover:bg-[#4a96ef] text-primary-foreground font-medium"
                disabled={isLoading}
              >
                {isLoading ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Вход...
                  </>
                ) : (
                  'Войти'
                )}
              </Button>
            </form>
          </CardContent>
        </Card>

        <p className="text-center text-muted-foreground text-xs mt-6">
          Демо: admin / admin123
        </p>
      </div>
    </div>
  )
}
