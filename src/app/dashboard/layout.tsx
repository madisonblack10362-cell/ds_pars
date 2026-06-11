'use client'

import { useState, useEffect, useRef } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import Link from 'next/link'
import {
  LayoutDashboard,
  Newspaper,
  Shield,
  ScrollText,
  Clock,
  LogOut,
  Menu,
  X,
  ChevronRight,
  Bell,
  BellOff,
  BellRing,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

const navItems = [
  { href: '/dashboard', label: 'Дашборд', icon: LayoutDashboard },
  { href: '/dashboard/moderation', label: 'Модерация', icon: Shield, badge: 'pending' },
  { href: '/dashboard/news', label: 'Новости', icon: Newspaper },
  { href: '/dashboard/schedule', label: 'Расписание', icon: Clock },
  { href: '/dashboard/logs', label: 'Логи', icon: ScrollText, badge: 'errors' },
]


export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [pendingCount, setPendingCount] = useState(0)
  const [errorCount, setErrorCount] = useState(0)
  const prevPendingRef = useRef(0)
  const [notifPermission, setNotifPermission] = useState<NotificationPermission | 'default'>('default')
  const [user, setUser] = useState<{ username: string; role: string } | null>(() => {
    if (typeof window === 'undefined') return null
    const userData = localStorage.getItem('auth_user')
    const token = localStorage.getItem('auth_token')
    if (!token || !userData) return null
    try {
      return JSON.parse(userData)
    } catch {
      return null
    }
  })
  const router = useRouter()
  const pathname = usePathname()

  useEffect(() => {
    const token = localStorage.getItem('auth_token')
    if (!token) {
      router.replace('/login')
    }
  }, [router])

  // Request notification permission on mount
  useEffect(() => {
    if (typeof window !== 'undefined' && 'Notification' in window) {
      if (Notification.permission === 'granted') {
        setNotifPermission('granted')
      } else if (Notification.permission === 'denied') {
        setNotifPermission('denied')
      }
    }
  }, [])

  const requestNotifPermission = async () => {
    if (typeof window === 'undefined' || !('Notification' in window)) return
    const perm = await Notification.requestPermission()
    setNotifPermission(perm)
  }

  // Fetch pending news count for the moderation badge + desktop notifications
  useEffect(() => {
    const token = localStorage.getItem('auth_token')
    if (!token) return

    let cancelled = false

    const fetchPendingCount = async () => {
      try {
        const res = await fetch(`/api/news?status=pending&limit=3&_t=${Date.now()}`)
        if (res.ok && !cancelled) {
          const data = await res.json()
          const total = data.total ?? data.news?.length ?? 0
          setPendingCount(total)

          // Desktop notification when new pending news appears
          if (
            typeof window !== 'undefined' &&
            'Notification' in window &&
            Notification.permission === 'granted' &&
            prevPendingRef.current < total &&
            prevPendingRef.current > 0 &&
            data.news?.length > 0
          ) {
            const latest = data.news[0]
            const title = latest?.title || latest?.original_text?.slice(0, 80) || 'Новая новость'
            const source = latest?.source_name || ''
            const typeLabels: Record<string, string> = {
              update: 'Новость',
              discussion: 'Обсуждение',
              content: 'Контент',
              bug: 'Баг',
              meme: 'Мем',
              event: 'Событие',
              mod: 'Мод',
              story: 'История',
              tip: 'Совет',
              guide: 'Гайд',
              other: 'Новость',
            }
            const typeLabel = typeLabels[latest?.news_type] || 'Новость'
            const n = new Notification(`📰 ${typeLabel} на модерации`, {
              body: `${title}${source ? `\nИсточник: ${source}` : ''}`,
              icon: '/icon-192.png',
              tag: 'dayz-moderation',
            })
            n.onclick = () => {
              window.focus()
              router.push('/dashboard/moderation')
              n.close()
            }
          }
          prevPendingRef.current = total
        }
      } catch {
        // silently fail
      }
    }

    const fetchErrorCount = async () => {
      try {
        const res = await fetch(`/api/logs?level=error&limit=1&_t=${Date.now()}`)
        if (res.ok && !cancelled) {
          const data = await res.json()
          setErrorCount(data.total ?? 0)
        }
      } catch {
        // silently fail
      }
    }

    fetchPendingCount()
    fetchErrorCount()
    const pendingInterval = setInterval(fetchPendingCount, 30000)
    const errorInterval = setInterval(fetchErrorCount, 30000)

    return () => {
      cancelled = true
      clearInterval(pendingInterval)
      clearInterval(errorInterval)
    }
  }, [router])

  const handleLogout = () => {
    localStorage.removeItem('auth_token')
    localStorage.removeItem('auth_user')
    router.replace('/login')
  }

  const isActive = (href: string) => {
    if (href === '/dashboard') return pathname === '/dashboard'
    return pathname.startsWith(href)
  }

  return (
    <div className="min-h-screen flex bg-background">
      {/* Mobile overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/60 lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        className={cn(
          'fixed inset-y-0 left-0 z-50 flex w-64 flex-col bg-[#151525] border-r border-[#2d3a54] transition-transform duration-300 lg:static lg:translate-x-0',
          sidebarOpen ? 'translate-x-0' : '-translate-x-full'
        )}
      >
        {/* Sidebar header */}
        <div className="flex items-center justify-between h-16 px-4 border-b border-[#2d3a54]">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-[#58a6ff]/10 flex items-center justify-center">
              <Shield className="w-4 h-4 text-[#58a6ff]" />
            </div>
            <span className="font-semibold text-sm text-foreground">DayZ Monitor</span>
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="lg:hidden text-muted-foreground hover:text-foreground hover:bg-secondary"
            onClick={() => setSidebarOpen(false)}
          >
            <X className="w-4 h-4" />
          </Button>
        </div>

        {/* Navigation */}
        <nav className="flex-1 overflow-y-auto py-4 px-3">
          <ul className="space-y-1">
            {navItems.map((item) => {
              const active = isActive(item.href)
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    onClick={() => setSidebarOpen(false)}
                    className={cn(
                      'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors group',
                      active
                        ? 'bg-[#58a6ff]/10 text-[#58a6ff]'
                        : 'text-muted-foreground hover:text-foreground hover:bg-secondary'
                    )}
                  >
                    <item.icon className={cn('w-4 h-4', active ? 'text-[#58a6ff]' : 'text-muted-foreground group-hover:text-foreground')} />
                    <span className="flex-1">{item.label}</span>
                    {item.badge === 'pending' && pendingCount > 0 && (
                      <span className="flex items-center justify-center min-w-[20px] h-5 px-1.5 rounded-full bg-red-500 text-[11px] font-bold text-white leading-none">
                        {pendingCount > 99 ? '99+' : pendingCount}
                      </span>
                    )}
                    {item.badge === 'errors' && errorCount > 0 && (
                      <span className="flex items-center justify-center min-w-[20px] h-5 px-1.5 rounded-full bg-red-500/80 text-[11px] font-bold text-white leading-none">
                        {errorCount > 99 ? '99+' : errorCount}
                      </span>
                    )}
                    {active && <ChevronRight className="w-3 h-3 text-[#58a6ff]" />}
                  </Link>
                </li>
              )
            })}
          </ul>
        </nav>

        {/* Notifications toggle */}
        <div className="px-3 pb-2">
          <button
            onClick={notifPermission === 'granted' ? undefined : requestNotifPermission}
            className={cn(
              'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors w-full',
              notifPermission === 'granted'
                ? 'text-emerald-400 hover:bg-emerald-500/10'
                : notifPermission === 'denied'
                  ? 'text-muted-foreground/50 cursor-default'
                  : 'text-muted-foreground hover:text-foreground hover:bg-secondary'
            )}
            title={
              notifPermission === 'granted'
                ? 'Уведомления включены'
                : notifPermission === 'denied'
                  ? 'Уведомления заблокированы в настройках браузера'
                  : 'Включить push-уведомления о модерации'
            }
          >
            {notifPermission === 'granted' ? (
              <BellRing className="w-4 h-4" />
            ) : notifPermission === 'denied' ? (
              <BellOff className="w-4 h-4" />
            ) : (
              <Bell className="w-4 h-4" />
            )}
            <span className="flex-1 text-left">
              {notifPermission === 'granted' ? 'Уведомления вкл.' : notifPermission === 'denied' ? 'Уведомления выкл.' : 'Включить уведомления'}
            </span>
            {notifPermission === 'granted' && (
              <span className="w-2 h-2 rounded-full bg-emerald-400" />
            )}
          </button>
        </div>

        {/* User info */}
        <div className="border-t border-[#2d3a54] p-4">
          <div className="flex items-center gap-3 mb-3">
            <div className="w-8 h-8 rounded-full bg-[#58a6ff]/20 flex items-center justify-center text-xs font-bold text-[#58a6ff]">
              {user?.username?.charAt(0).toUpperCase() || 'A'}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-foreground truncate">{user?.username || 'admin'}</p>
              <p className="text-xs text-muted-foreground">{user?.role === 'admin' ? 'Администратор' : 'Модератор'}</p>
            </div>
          </div>
          <Button
            variant="ghost"
            size="sm"
            className="w-full justify-start text-muted-foreground hover:text-destructive hover:bg-destructive/10 gap-2"
            onClick={handleLogout}
          >
            <LogOut className="w-4 h-4" />
            Выйти
          </Button>
        </div>
      </aside>

      {/* Main content */}
      <div className="flex-1 flex flex-col min-h-screen min-w-0" style={{maxWidth:'100vw',overflow:'hidden'}}>
        {/* Top bar for mobile */}
        <header className="sticky top-0 z-30 flex items-center h-14 px-4 bg-[#1a1a2e]/95 backdrop-blur-sm border-b border-[#2d3a54] lg:hidden">
          <Button
            variant="ghost"
            size="icon"
            className="text-muted-foreground hover:text-foreground hover:bg-secondary"
            onClick={() => setSidebarOpen(true)}
          >
            <Menu className="w-5 h-5" />
          </Button>
          <div className="flex items-center gap-2 ml-3">
            <Shield className="w-4 h-4 text-[#58a6ff]" />
            <span className="text-sm font-medium text-foreground">DayZ Monitor</span>
          </div>
        </header>

        <main className="flex-1 p-4 lg:p-6" style={{overflowY:'auto',overflowX:'hidden',maxWidth:'100vw',width:'100%'}}>
          {children}
        </main>
      </div>
    </div>
  )
}
