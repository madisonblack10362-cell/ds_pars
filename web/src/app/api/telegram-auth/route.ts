import { NextRequest, NextResponse } from 'next/server'
import { validateTelegramInitData } from '@/lib/telegram-auth'
import { generateToken } from '@/lib/auth'
import { db } from '@/lib/db'

export async function POST(request: NextRequest) {
  try {
    const { initData } = await request.json()

    if (!initData) {
      return NextResponse.json({ error: 'Init data is required' }, { status: 400 })
    }

    const botToken = process.env.TELEGRAM_BOT_TOKEN
    if (!botToken) {
      return NextResponse.json(
        { error: 'Telegram bot token not configured' },
        { status: 500 }
      )
    }

    const result = validateTelegramInitData(initData, botToken)
    if (!result.valid || !result.user) {
      return NextResponse.json({ error: result.error || 'Invalid init data' }, { status: 401 })
    }

    const tgUser = result.user

    // Check if user exists in database, or create new
    let user = await db.user.findUnique({
      where: { username: tgUser.username || `tg_${tgUser.id}` },
    })

    if (!user) {
      user = await db.user.create({
        data: {
          username: tgUser.username || `tg_${tgUser.id}`,
          password: '', // No password needed for Telegram users
          role: 'admin',
        },
      })
    }

    const token = generateToken({
      userId: user.id,
      username: user.username,
      role: user.role,
    })

    const response = NextResponse.json({
      token,
      user: {
        id: user.id,
        username: user.username,
        role: user.role,
        telegram: {
          id: tgUser.id,
          first_name: tgUser.first_name,
          username: tgUser.username,
        },
      },
    })

    response.cookies.set('token', token, {
      httpOnly: true,
      secure: process.env.NODE_ENV === 'production',
      sameSite: 'lax',
      maxAge: 60 * 60 * 24 * 7,
      path: '/',
    })

    return response
  } catch (error) {
    console.error('Telegram auth error:', error)
    return NextResponse.json({ error: 'Ошибка авторизации' }, { status: 500 })
  }
}
