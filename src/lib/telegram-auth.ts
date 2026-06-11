import crypto from 'crypto'

/**
 * Validates Telegram Web App initData
 * https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
 */
export function validateTelegramInitData(
  initData: string,
  botToken: string
): { valid: boolean; user?: TelegramUser; error?: string } {
  try {
    const params = new URLSearchParams(initData)
    const hash = params.get('hash')
    params.delete('hash')

    // Sort parameters alphabetically and create data-check-string
    const dataCheckString = Array.from(params.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([key, value]) => `${key}=${value}`)
      .join('\n')

    // Calculate HMAC-SHA256
    const secretKey = crypto
      .createHmac('sha256', 'WebAppData')
      .update(botToken)
      .digest()

    const calculatedHash = crypto
      .createHmac('sha256', secretKey)
      .update(dataCheckString)
      .digest('hex')

    if (calculatedHash !== hash) {
      return { valid: false, error: 'Invalid hash' }
    }

    // Parse auth_date and check expiry (max 1 hour)
    const authDate = parseInt(params.get('auth_date') || '0')
    const now = Math.floor(Date.now() / 1000)
    if (now - authDate > 3600) {
      return { valid: false, error: 'Init data expired' }
    }

    // Parse user
    const userStr = params.get('user')
    if (!userStr) {
      return { valid: false, error: 'No user data' }
    }

    const user = JSON.parse(userStr)
    return { valid: true, user }
  } catch (error) {
    return { valid: false, error: 'Failed to validate initData' }
  }
}

export interface TelegramUser {
  id: number
  first_name: string
  last_name?: string
  username?: string
  language_code?: string
}
