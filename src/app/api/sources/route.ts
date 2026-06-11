import { NextResponse } from 'next/server'
import { db } from '@/lib/db'

export async function GET() {
  try {
    const sources = await db.source.findMany({
      include: {
        _count: {
          select: { news: true },
        },
      },
      orderBy: { createdAt: 'desc' },
    })

    const formattedSources = sources.map((source) => ({
      id: source.id,
      name: source.serverName || source.sourceId,
      type: source.sourceType,
      enabled: source.enabled,
      config: JSON.parse(source.extra || '{}'),
      created_at: source.createdAt.toISOString(),
      last_check: null,
      news_count: source._count.news,
    }))

    return NextResponse.json({ sources: formattedSources })
  } catch (error) {
    console.error('Fetch sources error:', error)
    return NextResponse.json({ error: 'Ошибка получения источников' }, { status: 500 })
  }
}

export async function POST(request: Request) {
  try {
    const body = await request.json()
    const { name, type, config } = body

    if (!name || !type) {
      return NextResponse.json({ error: 'Название и тип обязательны' }, { status: 400 })
    }

    const id = `${type}-${Date.now()}`
    const source = await db.source.create({
      data: {
        id,
        sourceType: type,
        serverName: name,
        sourceId: id,
        channelName: '',
        enabled: true,
        extra: JSON.stringify(config || {}),
      },
    })

    return NextResponse.json({ success: true, source })
  } catch (error) {
    console.error('Create source error:', error)
    return NextResponse.json({ error: 'Ошибка сервера' }, { status: 500 })
  }
}

export async function PUT(request: Request) {
  try {
    const body = await request.json()
    const { id, name, type, config, enabled } = body

    if (!id) {
      return NextResponse.json({ error: 'ID источника обязателен' }, { status: 400 })
    }

    const data: Record<string, unknown> = {}
    if (name !== undefined) data.serverName = name
    if (type !== undefined) data.sourceType = type
    if (config !== undefined) data.extra = JSON.stringify(config)
    if (enabled !== undefined) data.enabled = enabled

    const source = await db.source.update({
      where: { id },
      data,
    })

    return NextResponse.json({ success: true, source })
  } catch (error) {
    console.error('Update source error:', error)
    return NextResponse.json({ error: 'Ошибка сервера' }, { status: 500 })
  }
}

export async function DELETE(request: Request) {
  try {
    const { searchParams } = new URL(request.url)
    const id = searchParams.get('id')

    if (!id) {
      return NextResponse.json({ error: 'ID источника обязателен' }, { status: 400 })
    }

    await db.source.delete({
      where: { id },
    })

    return NextResponse.json({ success: true, id })
  } catch (error) {
    console.error('Delete source error:', error)
    return NextResponse.json({ error: 'Ошибка сервера' }, { status: 500 })
  }
}
