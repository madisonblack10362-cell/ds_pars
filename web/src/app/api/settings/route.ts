import { NextResponse } from 'next/server'
import { db } from '@/lib/db'

const settingDefaults: Record<string, string> = {
  ai_model: 'meta/llama-3.1-8b-instruct',
  default_priority_threshold: 'medium',
  min_message_length: '50',
  auto_publish_high: 'false',
  auto_publish_medium: 'false',
  auto_publish_low: 'false',
  check_interval: '300',
  daily_summary_hour: '10',
  nvidia_api_url: 'https://integrate.api.nvidia.com/v1',
}

export async function GET() {
  try {
    const allSettings = await db.settings.findMany()
    const settings: Record<string, string> = {}

    // Start with defaults
    for (const [key, value] of Object.entries(settingDefaults)) {
      settings[key] = value
    }

    // Override with database values
    for (const s of allSettings) {
      settings[s.key] = s.value
    }

    return NextResponse.json(settings)
  } catch (error) {
    console.error('Fetch settings error:', error)
    return NextResponse.json({ error: 'Ошибка получения настроек' }, { status: 500 })
  }
}

export async function PUT(request: Request) {
  try {
    const body = await request.json()

    for (const [key, value] of Object.entries(body)) {
      await db.settings.upsert({
        where: { key },
        update: { value: String(value) },
        create: { key, value: String(value) },
      })
    }

    return NextResponse.json({ success: true, settings: body })
  } catch (error) {
    console.error('Update settings error:', error)
    return NextResponse.json({ error: 'Ошибка сервера' }, { status: 500 })
  }
}
