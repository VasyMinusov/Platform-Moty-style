import {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState,
} from 'react'

const NotificationsContext = createContext(null)

const STORAGE_KEY = 'ctf_notifications'
const MAX_KEPT = 50
const TOAST_DURATION_MS = 5000

let _seq = 1
function nextId() {
  return `${Date.now()}-${_seq++}`
}

function loadFromStorage() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function saveToStorage(items) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(items.slice(0, MAX_KEPT)))
  } catch {
    /* quota — игнорируем */
  }
}

export function NotificationsProvider({ children }) {
  const [items, setItems] = useState(loadFromStorage)
  const [toasts, setToasts] = useState([])
  const timersRef = useRef(new Map())

  // Сохраняем в localStorage на каждое изменение.
  useEffect(() => {
    saveToStorage(items)
  }, [items])

  // Сбрасываем таймеры при размонтировании.
  useEffect(() => {
    const timers = timersRef.current
    return () => {
      for (const t of timers.values()) clearTimeout(t)
      timers.clear()
    }
  }, [])

  const dismissToast = useCallback((id) => {
    setToasts((t) => t.filter((x) => x.id !== id))
    const timer = timersRef.current.get(id)
    if (timer) {
      clearTimeout(timer)
      timersRef.current.delete(id)
    }
  }, [])

  /**
   * push({ type, title, message, level, link, meta })
   *   type    — короткий код события, например 'solve.created' или 'team.invite'
   *   title   — заголовок уведомления
   *   message — текст
   *   level   — 'info' | 'success' | 'warning' | 'danger' (по умолчанию 'info')
   *   link    — необязательный путь для перехода по клику
   *   meta    — произвольный объект
   *   silent  — не показывать тост, только запись в список
   */
  const push = useCallback((payload) => {
    const id = nextId()
    const now = new Date().toISOString()
    const notification = {
      id,
      type: payload.type || 'generic',
      title: payload.title || 'Уведомление',
      message: payload.message || '',
      level: payload.level || 'info',
      link: payload.link || null,
      meta: payload.meta || null,
      created_at: now,
      read: false,
    }

    setItems((prev) => [notification, ...prev].slice(0, MAX_KEPT))

    if (!payload.silent) {
      const toast = { ...notification }
      setToasts((t) => [...t, toast])
      const timer = setTimeout(() => dismissToast(id), TOAST_DURATION_MS)
      timersRef.current.set(id, timer)
    }

    return id
  }, [dismissToast])

  const markRead = useCallback((id) => {
    setItems((prev) => prev.map((n) => (n.id === id ? { ...n, read: true } : n)))
  }, [])

  const markAllRead = useCallback(() => {
    setItems((prev) => prev.map((n) => ({ ...n, read: true })))
  }, [])

  const remove = useCallback((id) => {
    setItems((prev) => prev.filter((n) => n.id !== id))
  }, [])

  const clearAll = useCallback(() => {
    setItems([])
  }, [])

  const unreadCount = useMemo(
    () => items.reduce((acc, n) => acc + (n.read ? 0 : 1), 0),
    [items],
  )

  const value = useMemo(
    () => ({
      items,
      toasts,
      unreadCount,
      push,
      markRead,
      markAllRead,
      remove,
      clearAll,
      dismissToast,
    }),
    [items, toasts, unreadCount, push, markRead, markAllRead, remove, clearAll, dismissToast],
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