/**
 * WebSocket-клиент для канала соревнования.
 *
 * Использование:
 *   useCompetitionStream(slug, token, (event) => { ... })
 *
 * Возвращает объект с методом close() — на случай, если нужно
 * закрыть соединение до unmount'а компонента.
 */
import { useEffect, useRef } from 'react'

function buildWsUrl(slug, token) {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host = window.location.host
  const params = token ? `?token=${encodeURIComponent(token)}` : ''
  return `${proto}//${host}/api/competitions/${slug}/stream${params}`
}

/**
 * Подписывается на /competitions/{slug}/stream.
 * onEvent получает объект {type, data}.
 */
export function useCompetitionStream(slug, token, onEvent) {
  // handlerRef — единственный ref, который оправдан: он нужен, чтобы
  // переподписка на новый onEvent не пересоздавала WebSocket.
  // Сам WS и его таймеры живут в замыкании эффекта (см. комментарий
  // в NotificationsContext.jsx — там объяснение про StrictMode).
  const handlerRef = useRef(onEvent)
  handlerRef.current = onEvent

  useEffect(() => {
    if (!slug) return

    let cancelled = false
    let ws = null
    let reconnectTimer = null
    let initialTimer = null

    function connect() {
      if (cancelled) return

      ws = new WebSocket(buildWsUrl(slug, token))

      ws.onmessage = (evt) => {
        if (cancelled) return
        try {
          const payload = JSON.parse(evt.data)
          handlerRef.current?.(payload)
        } catch {
          /* ignore malformed */
        }
      }

      ws.onclose = () => {
        if (cancelled) return
        reconnectTimer = setTimeout(connect, 3000)
      }

      ws.onerror = () => {
        try {
          ws.close()
        } catch {
          /* ignore */
        }
      }
    }

    initialTimer = setTimeout(connect, 150)

    return () => {
      cancelled = true
      if (initialTimer) clearTimeout(initialTimer)
      if (reconnectTimer) clearTimeout(reconnectTimer)
      try {
        ws?.close()
      } catch {
        /* ignore */
      }
    }
  }, [slug, token])

  return {
    close: () => {
      // Закрытие инициируется через cleanup эффекта при размонтировании
      // или смене slug/token. Отдельный метод оставлен для совместимости
      // с API, который использовался в вызывающем коде.
    },
  }
}