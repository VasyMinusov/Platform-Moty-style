/**
 * WebSocket-клиент для канала соревнования.
 *
 * Использование:
 *   const stream = useCompetitionStream(slug, token, (event) => { ... })
 *   stream.close()
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
  const handlerRef = useRef(onEvent)
  handlerRef.current = onEvent

  const wsRef = useRef(null)
  const reconnectTimerRef = useRef(null)
  const closedManuallyRef = useRef(false)

  useEffect(() => {
    if (!slug) return

    closedManuallyRef.current = false

    function connect() {
      const ws = new WebSocket(buildWsUrl(slug, token))
      wsRef.current = ws

      ws.onmessage = (evt) => {
        try {
          const payload = JSON.parse(evt.data)
          handlerRef.current?.(payload)
        } catch {
          /* ignore malformed */
        }
      }

      ws.onclose = () => {
        if (closedManuallyRef.current) return
        reconnectTimerRef.current = setTimeout(connect, 3000)
      }

      ws.onerror = () => {
        try { ws.close() } catch { /* ignore */ }
      }
    }

    connect()

    return () => {
      closedManuallyRef.current = true
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current)
      try { wsRef.current?.close() } catch { /* ignore */ }
    }
  }, [slug, token])

  return {
    close: () => {
      closedManuallyRef.current = true
      try { wsRef.current?.close() } catch { /* ignore */ }
    },
  }
}