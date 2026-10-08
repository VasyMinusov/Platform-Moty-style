import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useNotifications } from '../context/NotificationsContext'
import './NotificationsBell.css'

const LEVEL_ICONS = {
  info: 'ℹ',
  success: '✓',
  warning: '⚠',
  danger: '✕',
}

function relativeTime(iso) {
  const diff = Date.now() - new Date(iso).getTime()
  const s = Math.floor(diff / 1000)
  if (s < 60) return 'только что'
  const m = Math.floor(s / 60)
  if (m < 60) return `${m} мин назад`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h} ч назад`
  const d = Math.floor(h / 24)
  if (d < 7) return `${d} дн назад`
  return new Date(iso).toLocaleDateString('ru-RU')
}

export default function NotificationsBell() {
  const {
    items, unreadCount, markRead, markAllRead, remove, clearAll,
  } = useNotifications()
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  const navigate = useNavigate()

  // Закрытие по клику вне панели.
  useEffect(() => {
    if (!open) return
    function onDown(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
    }
    function onEsc(e) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onEsc)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onEsc)
    }
  }, [open])

  function handleItemClick(n) {
    if (!n.read) markRead(n.id)
    if (n.link) {
      setOpen(false)
      navigate(n.link)
    }
  }

  return (
    <div className="nbell" ref={ref}>
      <button
        className={`nbell-btn${unreadCount > 0 ? ' has-unread' : ''}`}
        aria-label="Уведомления"
        onClick={() => setOpen((v) => !v)}
      >
        <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
          <path
            d="M12 2a6 6 0 0 0-6 6v4l-1.5 3.5h15L18 12V8a6 6 0 0 0-6-6Zm0 20a2 2 0 0 0 2-2h-4a2 2 0 0 0 2 2Z"
            fill="currentColor"
          />
        </svg>
        {unreadCount > 0 && (
          <span className="nbell-badge mono">
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div className="nbell-panel" role="dialog" aria-label="Уведомления">
          <header className="nbell-head">
            <span className="eyebrow">уведомления</span>
            <div className="nbell-head-actions">
              {items.length > 0 && unreadCount > 0 && (
                <button className="nbell-link" onClick={markAllRead}>
                  прочитать все
                </button>
              )}
              {items.length > 0 && (
                <button className="nbell-link danger" onClick={clearAll}>
                  очистить
                </button>
              )}
            </div>
          </header>

          {items.length === 0 ? (
            <div className="nbell-empty">Пока уведомлений нет.</div>
          ) : (
            <ul className="nbell-list">
              {items.map((n) => (
                <li
                  key={n.id}
                  className={`nbell-item level-${n.level}${n.read ? ' read' : ''}`}
                  onClick={() => handleItemClick(n)}
                >
                  <span className="nbell-icon" aria-hidden="true">
                    {LEVEL_ICONS[n.level] || LEVEL_ICONS.info}
                  </span>
                  <div className="nbell-item-body">
                    <div className="nbell-item-title">{n.title}</div>
                    {n.message && <div className="nbell-item-msg">{n.message}</div>}
                    <div className="nbell-item-time mono">{relativeTime(n.created_at)}</div>
                  </div>
                  <button
                    className="nbell-remove"
                    aria-label="Удалить"
                    onClick={(e) => {
                      e.stopPropagation()
                      remove(n.id)
                    }}
                  >
                    ×
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}