/**
 * Image Storage Utility
 *
 * Downloads Discord CDN images (and other external URLs) and converts
 * them to base64 data URLs for permanent storage in the database.
 * Discord CDN attachment URLs expire after ~24 hours — by downloading
 * immediately on ingestion, images become permanent.
 *
 * Limits:
 *   - Max 3 MB per image (raw binary)
 *   - Max 5 images per news item
 *   - 10 s timeout per image download
 */

const MAX_IMAGE_SIZE = 3 * 1024 * 1024 // 3 MB
const MAX_IMAGES = 5
const DOWNLOAD_TIMEOUT = 10_000 // 10 seconds
const MAX_DATA_URL_LENGTH = 4 * 1024 * 1024 // ~3 MB in base64

function isExternalUrl(url: string): boolean {
  if (!url || typeof url !== 'string') return false
  return url.startsWith('http://') || url.startsWith('https://')
}

function isAlreadyDataUrl(url: string): boolean {
  return url.startsWith('data:')
}

/**
 * Download an image from a URL and return a base64 data URL.
 * Returns null if download fails, times out, or image is too large.
 */
export async function downloadImageAsDataUrl(url: string): Promise<string | null> {
  try {
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), DOWNLOAD_TIMEOUT)

    const response = await fetch(url, {
      signal: controller.signal,
      headers: {
        'User-Agent': 'DayZMonitor/1.0 (+https://dayz-monitor-web.vercel.app)',
        'Accept': 'image/*',
      },
      redirect: 'follow',
    })

    clearTimeout(timeout)

    if (!response.ok) {
      console.warn(`[image-storage] Failed to download ${url}: HTTP ${response.status}`)
      return null
    }

    // Check content length if available
    const contentLength = response.headers.get('content-length')
    if (contentLength && parseInt(contentLength) > MAX_IMAGE_SIZE) {
      console.warn(`[image-storage] Image too large: ${contentLength} bytes (max ${MAX_IMAGE_SIZE})`)
      return null
    }

    const buffer = await response.arrayBuffer()

    if (buffer.byteLength > MAX_IMAGE_SIZE) {
      console.warn(`[image-storage] Image too large after download: ${buffer.byteLength} bytes`)
      return null
    }

    const base64 = Buffer.from(buffer).toString('base64')

    // Determine MIME type
    const contentType = response.headers.get('content-type') || 'image/png'
    const mimeType = contentType.split(';')[0].trim()

    const dataUrl = `data:${mimeType};base64,${base64}`

    if (dataUrl.length > MAX_DATA_URL_LENGTH) {
      console.warn(`[image-storage] Data URL too long: ${dataUrl.length} chars`)
      return null
    }

    return dataUrl
  } catch (error) {
    console.warn(`[image-storage] Error downloading ${url}:`, (error as Error)?.message || error)
    return null
  }
}

/**
 * Process an array of image URLs:
 *   - Downloads external URLs (Discord CDN, etc.) and converts to data URLs
 *   - Keeps data URLs as-is (already permanent)
 *   - Skips invalid URLs
 *   - Respects MAX_IMAGES limit
 *
 * Returns the processed array ready for JSON storage.
 */
export async function processImageUrls(imageUrls: string[]): Promise<string[]> {
  if (!Array.isArray(imageUrls)) return []

  const result: string[] = []
  const toDownload: string[] = []

  for (const url of imageUrls) {
    if (!url || typeof url !== 'string') continue

    if (isAlreadyDataUrl(url)) {
      // Already permanent — keep as-is
      result.push(url)
      if (result.length >= MAX_IMAGES) break
    } else if (isExternalUrl(url)) {
      // External URL — need to download
      toDownload.push(url)
      if (toDownload.length + result.length >= MAX_IMAGES) break
    }
  }

  // Download external images concurrently (max 3 at a time)
  const batchSize = 3
  for (let i = 0; i < toDownload.length && result.length < MAX_IMAGES; i += batchSize) {
    const batch = toDownload.slice(i, i + batchSize)
    const downloaded = await Promise.all(batch.map(downloadImageAsDataUrl))

    for (const dataUrl of downloaded) {
      if (dataUrl && result.length < MAX_IMAGES) {
        result.push(dataUrl)
      }
    }
  }

  console.log(`[image-storage] Processed ${imageUrls.length} URLs -> ${result.length} permanent images`)
  return result
}
