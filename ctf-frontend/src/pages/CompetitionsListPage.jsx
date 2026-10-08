import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import { useAuth } from '../context/AuthContext'
import './CompetitionsListPage.css'

const STATUS_LABEL = {
  draft: 'черновик',
  announced: 'анонс',
  registration_open: 'регистрация открыта',
  registration_closed: 'регистрация закрыта',
  running: 'идёт',
  paused: 'пауза',
  finished: 'завершено',
  cancelled: 'отменено',
}

function formatDateRange(start, end) {
  if (!start && !end) return '—'
  const fmt = (iso) =>
    new Date(iso).toLocaleString('ru-RU', {
      day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
    })
  if (start && end) return `${fmt(start)} → ${fmt(end)}`
  return start ? `с ${fmt(start)}` : `до ${fmt(end)}`
}

function formatCountdown(start, end, status) {
  const now = Date.now()
  const toDate = (iso) => (iso ? new Date(iso).getTime() : null)
  const s = toDate(start)
  const e = toDate(end)

  if (status === 'running' && e) {
    const diff = e - now
    if (diff <= 0) return 'скоро конец'
    const h = Math.floor(diff / 3600000)
    const m = Math.floor((diff % 3600000) / 60000)
    return `осталось ${h}ч ${m}м`
  }
  if (status === 'registration_open' && e) {
    const diff = e - now
    if (diff > 0) {
      const h = Math.floor(diff / 3600000)
      const m = Math.floor((diff % 3600000) / 60000)
      return `регистрация: ${h}ч ${m}м`
    }
  }
  if (status === 'announced' && s) {
    const diff = s - now
    if (diff > 0) {
      const d = Math.floor(diff / 86400000)
      const h = Math.floor((diff % 86400000) / 3600000)
      return `старт через ${d}д ${h}ч`
    }
  }
  return null
}

export default function CompetitionsListPage() {
  const { isAuthenticated } = useAuth()
  const navigate = useNavigate()
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [statusFilter, setStatusFilter] = useState('all')

  useEffect(() => { load() }, [])

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const data = await api.listCompetitions()
      setItems(data)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось загрузить соревнования')
    } finally {
      setLoading(false)
    }
  }

  const visible = useMemo(() => {
    if (statusFilter === 'all') return items
    if (statusFilter === 'active') {
      return items.filter((c) => ['running', 'paused', 'registration_open'].includes(c.status))
    }
    if (statusFilter === 'upcoming') {
      return items.filter((c) => ['announced'].includes(c.status))
    }
    if (statusFilter === 'finished') {
      return items.filter((c) => ['finished', 'cancelled'].includes(c.status))
    }
    return items
  }, [items, statusFilter])

  return (
    <div>
      <div className="page-head">
        <div>
          <span className="eyebrow">реестр соревнований</span>
          <h1>Соревнования</h1>
        </div>
        {isAuthenticated && (
          <Link to="/challenges" className="btn">К заданиям</Link>
        )}
      </div>

      <div className="filters">
        <div className="filter-group">
          {[
            ['all', 'все'],
            ['active', 'активные'],
            ['upcoming', 'анонсы'],
            ['finished', 'архив'],
          ].map(([value, label]) => (
            <button
              key={value}
              className={`filter-chip${statusFilter === value ? ' active' : ''}`}
              onClick={() => setStatusFilter(value)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {error && <div className="alert">{error}</div>}

      {loading ? (
        <p className="mono" style={{ color: 'var(--text-dim)' }}>загрузка…</p>
      ) : visible.length === 0 ? (
        <div className="empty-state">
          <p>Соревнований по выбранному фильтру нет.</p>
        </div>
      ) : (
        <div className="comp-grid">
          {visible.map((c) => {
            const countdown = formatCountdown(c.starts_at, c.ends_at, c.status)
            const statusLabel = STATUS_LABEL[c.status] || c.status
            return (
              <article
                key={c.id}
                className={`comp-card status-${c.status}`}
                onClick={() => navigate(`/competitions/${c.slug}`)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') navigate(`/competitions/${c.slug}`)
                }}
              >
                <header className="comp-card-head">
                  <span className={`comp-status comp-status-${c.status}`}>
                    {statusLabel}
                  </span>
                  <span className="comp-mode mono">
                    {c.mode === 'individual' && 'индивид.'}
                    {c.mode === 'team' && 'команды'}
                    {c.mode === 'both' && 'индивид. + команды'}
                  </span>
                </header>

                <h3 className="comp-title">{c.title}</h3>
                <p className="comp-summary">{c.summary || 'Без описания'}</p>

                <div className="comp-dates mono">
                  {formatDateRange(c.starts_at, c.ends_at)}
                </div>

                {countdown && (
                  <div className="comp-countdown mono">{countdown}</div>
                )}

                {(c.min_team_size || c.max_team_size) && (
                  <div className="comp-team-size mono">
                    команда: {c.min_team_size || '?'}–{c.max_team_size || '?'}
                  </div>
                )}
              </article>
            )
          })}
        </div>
      )}
    </div>
  )
}