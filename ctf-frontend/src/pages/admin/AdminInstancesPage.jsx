import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../../api/client'
import './AdminCompetitions.css'

function formatDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('ru-RU')
}

function formatCountdown(expiresAt) {
  const diff = new Date(expiresAt).getTime() - Date.now()
  if (diff <= 0) return 'истёк'
  const totalSec = Math.floor(diff / 1000)
  const m = Math.floor(totalSec / 60)
  const s = totalSec % 60
  return `${m}м ${String(s).padStart(2, '0')}с`
}

export default function AdminInstancesPage() {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [onlyAlive, setOnlyAlive] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.adminListInstances({ only_alive: onlyAlive })
      setItems(data.items || [])
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Ошибка загрузки')
    } finally {
      setLoading(false)
    }
  }, [onlyAlive])

  useEffect(() => {
    load()
  }, [load])

  async function stopOne(id) {
    if (!confirm(`Остановить инстанс #${id}?`)) return
    setBusy(true)
    setError(null)
    try {
      await api.adminStopInstance(id)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Ошибка')
    } finally {
      setBusy(false)
    }
  }

  async function stopAll() {
    if (!confirm(`Остановить ВСЕ ${items.length} инстансов?`)) return
    setBusy(true)
    setError(null)
    try {
      const res = await api.adminStopAllInstances()
      alert(`Остановлено: ${res.stopped} (ошибок: ${res.failed})`)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Ошибка')
    } finally {
      setBusy(false)
    }
  }

  async function reapExpired() {
    setBusy(true)
    setError(null)
    try {
      const res = await api.reapInstances()
      alert(`Остановлено просроченных: ${res.stopped}`)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Ошибка')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <div className="page-head">
        <div>
          <span className="eyebrow">служебный контур</span>
          <h1>Инстансы</h1>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <button className="btn" onClick={load} disabled={loading || busy}>
            Обновить
          </button>
          <button className="btn" onClick={reapExpired} disabled={busy}>
            Остановить просроченные
          </button>
          <button
            className="btn btn-danger"
            onClick={stopAll}
            disabled={busy || items.length === 0}
          >
            Остановить все
          </button>
        </div>
      </div>

      <div className="adm-toolbar">
        <label className="mono" style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <input
            type="checkbox"
            checked={onlyAlive}
            onChange={(e) => setOnlyAlive(e.target.checked)}
          />
          только живые (docker inspect)
        </label>
        <span className="mono" style={{ color: 'var(--text-dim)' }}>
          всего: {items.length}
        </span>
      </div>

      {error && <div className="alert">{error}</div>}

      {loading ? (
        <p className="mono" style={{ color: 'var(--text-dim)' }}>загрузка…</p>
      ) : items.length === 0 ? (
        <div className="empty-state">
          <p>Нет запущенных инстансов.</p>
        </div>
      ) : (
        <div className="adm-table-wrap">
          <table className="adm-table">
            <thead>
              <tr>
                <th>#</th>
                <th>scope</th>
                <th>пользователь</th>
                <th>задание</th>
                <th>порт</th>
                <th>URL</th>
                <th>started</th>
                <th>expires</th>
                <th>alive</th>
                <th aria-label="Действия" />
              </tr>
            </thead>
            <tbody>
              {items.map((it) => (
                <tr key={it.id}>
                  <td className="mono">#{it.id}</td>
                  <td className="mono" style={{ fontSize: 11 }}>
                    {it.scope === 'competition' ? `comp:${it.competition_slug}` : 'global'}
                  </td>
                  <td>{it.username || `user:${it.user_id}`}</td>
                  <td>
                    <span className="mono" style={{ fontSize: 12 }}>{it.challenge_slug}</span>
                    <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                      {it.challenge_title}
                    </div>
                  </td>
                  <td className="mono">{it.host_port}</td>
                  <td>
                    <a
                      href={it.url}
                      target="_blank"
                      rel="noreferrer"
                      className="mono"
                      style={{ fontSize: 11 }}
                    >
                      {it.url} ↗
                    </a>
                  </td>
                  <td className="mono" style={{ fontSize: 11 }}>{formatDate(it.started_at)}</td>
                  <td className="mono" style={{ fontSize: 11 }}>
                    {formatDate(it.expires_at)}
                    <div style={{ color: it.is_expired ? 'var(--danger)' : 'var(--text-faint)' }}>
                      {formatCountdown(it.expires_at)}
                    </div>
                  </td>
                  <td className="mono">
                    {it.is_alive === true && '✓'}
                    {it.is_alive === false && '✗'}
                    {it.is_alive === null && '—'}
                  </td>
                  <td>
                    <button
                      className="adm-btn-mini danger"
                      disabled={busy}
                      onClick={() => stopOne(it.id)}
                    >
                      Остановить
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}