import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import './AdminCompetitions.css'

export default function AdminCompetitionAppealsPage() {
  const { slug } = useParams()
  const [items, setItems] = useState([])
  const [statusFilter, setStatusFilter] = useState('open')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [active, setActive] = useState(null)
  const [resolution, setResolution] = useState('')

  useEffect(() => { load() }, [slug, statusFilter])

  async function load() {
    setLoading(true); setError(null)
    try {
      setItems(await api.adminListAppeals(slug, statusFilter || undefined))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Ошибка')
    } finally { setLoading(false) }
  }

  async function resolve(status) {
    if (!active) return
    setBusy(true); setError(null)
    try {
      await api.adminResolveAppeal(slug, active.id, { status, resolution: resolution || null })
      setActive(null); setResolution('')
      await load()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Ошибка')
    } finally { setBusy(false) }
  }

  return (
    <div>
      <div className="page-head">
        <div>
          <span className="eyebrow mono">{slug}</span>
          <h1>Апелляции</h1>
        </div>
        <Link to={`/admin/competitions`} className="btn">← К списку</Link>
      </div>

      <div className="adm-toolbar">
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="">все</option>
          <option value="open">открытые</option>
          <option value="accepted">принятые</option>
          <option value="rejected">отклонённые</option>
        </select>
        <button className="btn" onClick={load}>Обновить</button>
      </div>

      {error && <div className="alert">{error}</div>}

      {loading ? (
        <p className="mono" style={{ color: 'var(--text-dim)' }}>загрузка…</p>
      ) : items.length === 0 ? (
        <div className="empty-state"><p>Апелляций нет.</p></div>
      ) : (
        <div className="adm-table-wrap">
          <table className="adm-table">
            <thead>
              <tr>
                <th>#</th>
                <th>пользователь</th>
                <th>задание</th>
                <th>статус</th>
                <th>сообщение</th>
                <th>создано</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map((a) => (
                <tr key={a.id}>
                  <td className="mono">#{a.id}</td>
                  <td>{a.username}</td>
                  <td className="mono">{a.challenge_id ?? '—'}</td>
                  <td><span className="adm-badge">{a.status}</span></td>
                  <td style={{ maxWidth: 320, fontSize: 12, color: 'var(--text-dim)' }}>{a.message}</td>
                  <td className="mono" style={{ fontSize: 11 }}>
                    {new Date(a.created_at).toLocaleString('ru-RU')}
                  </td>
                  <td>
                    <button
                      className="adm-btn-mini"
                      disabled={busy || a.status !== 'open'}
                      onClick={() => { setActive(a); setResolution('') }}
                    >
                      Рассмотреть
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {active && (
        <div className="adm-card" style={{ marginTop: 20 }}>
          <h3>Апелляция #{active.id} от {active.username}</h3>
          <p style={{ color: 'var(--text-dim)', fontSize: 13 }}>{active.message}</p>
          <div className="wiz-field">
            <label>Резолюция (комментарий)</label>
            <input value={resolution} onChange={(e) => setResolution(e.target.value)} />
          </div>
          <div style={{ display: 'flex', gap: 10 }}>
            <button className="btn btn-primary" disabled={busy} onClick={() => resolve('accepted')}>
              Принять
            </button>
            <button className="btn btn-danger" disabled={busy} onClick={() => resolve('rejected')}>
              Отклонить
            </button>
            <button className="btn" onClick={() => setActive(null)}>Отмена</button>
          </div>
        </div>
      )}
    </div>
  )
}