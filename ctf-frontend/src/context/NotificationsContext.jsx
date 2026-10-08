import {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState,
} from 'react'
import { api } from '../api/client'
import { useAuth } from './AuthContext'

const NotificationsContext = createContext(null)

const TOAST_DURATION_MS = 5000

let _seq = 1
function nextId() {
  return `local-${Date.now()}-${_seq++}`
}

function buildNotificationsWsUrl(token) {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host = window.location.host
  const params = token ? `?token=${encodeURIComponent(token)}` : ''
  return `${proto}//${host}/api/notifications/stream${params}`
}

export function NotificationsProvider({ children }) {
  const { token, isAuthenticated } = useAuth()

  const [items, setItems] = useState([])
  const [unreadCount, setUnreadCount] = useState(0)
  const [toasts, setToasts] = useState([])

  const wsRef = useRef(null)
  const reconnectTimerRef = useRef(null)
  const closedManuallyRef = useRef(false)
  const timersRef = useRef(new Map())

  // ── Toasts ────────────────────────────────────────────────────────

  const dismissToast = useCallback((id) => {
    setToasts((t) => t.filter((x) => x.id !== id))
    const timer = timersRef.current.get(id)
    if (timer) {
      clearTimeout(timer)
      timersRef.current.delete(id)
    }
  }, [])

  const showToast = useCallback((payload) => {
    const id = payload.id || nextId()
    const toast = {
      id,
      level: payload.level || 'info',
      title: payload.title || 'Уведомление',
      message: payload.message || '',
      link: payload.link || null,
    }
    setToasts((t) => [...t, toast])
    const timer = setTimeout(() => dismissToast(id), TOAST_DURATION_MS)
    timersRef.current.set(id, timer)
  }, [dismissToast])

  useEffect(() => {
    const timers = timersRef.current
    return () => {
      for (const t of timers.values()) clearTimeout(t)
      timers.clear()
    }
  }, [])

  // ── Загрузка списка при входе ────────────────────────────────────

  const reload = useCallback(async () => {
    if (!isAuthenticated) {
      setItems([])
      setUnreadCount(0)
      return
    }
    try {
      const data = await api.listNotifications({ limit: 50 })
      setItems(data.items || [])
      setUnreadCount(data.unread_count || 0)
    } catch {
      /* ignore */
    }
  }, [isAuthenticated])

  useEffect(() => {
    reload()
  }, [reload])

  // ── WebSocket ────────────────────────────────────────────────────

  useEffect(() => {
    if (!token || !isAuthenticated) return

    closedManuallyRef.current = false

    function connect() {
      const ws = new WebSocket(buildNotificationsWsUrl(token))
      wsRef.current = ws

      ws.onmessage = (evt) => {
        try {
          const payload = JSON.parse(evt.data)
          if (payload.type === 'notifications.hello') {
            setUnreadCount(payload.data?.unread_count ?? 0)
            return
          }
          if (payload.type === 'notification.created') {
            const n = payload.data || {}
            const item = {
              id: n.id,
              type: n.notification_type || 'generic',
              title: n.title,
              message: n.message,
              level: n.level || 'info',
              link: n.link || null,
              payload_json: n.payload || {},
              read: false,
              created_at: n.created_at || new Date().toISOString(),
            }
            setItems((prev) => [item, ...prev].slice(0, 100))
            setUnreadCount((c) => c + 1)
            showToast(item)
          }
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
  }, [token, isAuthenticated, showToast])

  // ── Публичный API ────────────────────────────────────────────────

  const push = useCallback((payload) => {
    // Локальный push — на случай, если хотим уведомить без бэка.
    const id = payload.id || nextId()
    const item = {
      id,
      type: payload.type || 'generic',
      title: payload.title || 'Уведомление',
      message: payload.message || '',
      level: payload.level || 'info',
      link: payload.link || null,
      payload_json: payload.meta || {},
      read: false,
      created_at: new Date().toISOString(),
    }
    setItems((prev) => [item, ...prev].slice(0, 100))
    setUnreadCount((c) => c + 1)
    if (!payload.silent) showToast(item)
    return id
  }, [showToast])

  const markRead = useCallback(async (id) => {
    setItems((prev) => prev.map((n) => (n.id === id ? { ...n, read: true } : n)))
    setUnreadCount((c) => Math.max(0, c - 1))
    try { await api.markNotificationRead(id) } catch { /* ignore */ }
  }, [])

  const markAllRead = useCallback(async () => {
    setItems((prev) => prev.map((n) => ({ ...n, read: true })))
    setUnreadCount(0)
    try { await api.markAllNotificationsRead() } catch { /* ignore */ }
  }, [])

  const remove = useCallback(async (id) => {
    setItems((prev) => prev.filter((n) => n.id !== id))
    try { await api.deleteNotification(id) } catch { /* ignore */ }
  }, [])

  const clearAll = useCallback(async () => {
    setItems([])
    setUnreadCount(0)
    try { await api.clearNotifications() } catch { /* ignore */ }
  }, [])

  const value = useMemo(
    () => ({
      items, toasts, unreadCount,
      push, markRead, markAllRead, remove, clearAll,
      dismissToast, reload,
    }),
    [items, toasts, unreadCount, push, markRead, markAllRead, remove, clearAll, dismissToast, reload],
  )

  return (
    <NotificationsContext.Provider value={value}>
      {children}
    </NotificationsContext.Provider>
  )
}

export function useNotifications() {
  const ctx = useContext(NotificationsContext)
  if (!ctx) throw new Error('useNotifications must be used inside <NotificationsProvider>')
  return ctx
}