import { useNavigate } from 'react-router-dom'
import { useNotifications } from '../context/NotificationsContext'
import './Toasts.css'

const ICONS = {
  info: 'ℹ',
  success: '✓',
  warning: '⚠',
  danger: '✕',
}

export default function Toasts() {
  const { toasts, dismissToast } = useNotifications()
  const navigate = useNavigate()

  if (toasts.length === 0) return null

  return (
    <div className="toasts" aria-live="polite">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={`toast toast-${t.level}`}
          onClick={() => {
            if (t.link) {
              navigate(t.link)
              dismissToast(t.id)
            }
          }}
          role={t.link ? 'button' : undefined}
        >
          <span className="toast-icon" aria-hidden="true">
            {ICONS[t.level] || ICONS.info}
          </span>
          <div className="toast-body">
            <div className="toast-title">{t.title}</div>
            {t.message && <div className="toast-message">{t.message}</div>}
          </div>
          <button
            className="toast-close"
            aria-label="Закрыть"
            onClick={(e) => {
              e.stopPropagation()
              dismissToast(t.id)
            }}
          >
            ×
          </button>
        </div>
      ))}
    </div>
  )
}