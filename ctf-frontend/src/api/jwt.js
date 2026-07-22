/**
 * Бэкенд не отдаёт отдельный /auth/me, поэтому всё, что мы знаем о
 * пользователе на фронте — это то, что зашито в payload JWT (sub, exp).
 * Декодируем его локально, ничего никуда не отправляя.
 */
export function decodeJwt(token) {
  try {
    const [, payload] = token.split('.')
    const normalized = payload.replace(/-/g, '+').replace(/_/g, '/')
    const padded = normalized.padEnd(normalized.length + ((4 - (normalized.length % 4)) % 4), '=')
    const json = decodeURIComponent(
      atob(padded)
        .split('')
        .map((c) => '%' + c.charCodeAt(0).toString(16).padStart(2, '0'))
        .join('')
    )
    return JSON.parse(json)
  } catch {
    return null
  }
}

export function isTokenExpired(token) {
  const payload = decodeJwt(token)
  if (!payload?.exp) return true
  return Date.now() >= payload.exp * 1000
}


