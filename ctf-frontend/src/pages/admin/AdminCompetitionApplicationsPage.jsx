import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import './AdminCompetitions.css'

const STATUS_LABEL = {
  pending: 'ожидает',
  approved: 'одобрена',
  rejected: 'отклонена',
  withdrawn: 'отозвана',
  waitlist: 'лист ожидания',
  team_pending: 'команда не набрана',
  team_rejected: 'команда отклонена',
}

export default function AdminCompetitionApplicationsPage() {
  const { slug } = useParams()
  const [items, setItems] = useState([])
  const [statusFilter, setStatusFilter] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [decision, setDecision] = useState(null) // {appId, status}
  const [comment, setComment] = useState('')

  useEffect(() => { load() }, [slug, statusFilter])

  async function load() {
    setLoading(true); setError(null)
    try {
      setItems(await api.adminListApplications(slug, statusFilter || undefined))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Ошибка')
    } finally { setLoading(false) }
  }

  async function submitDecision() {
    if (!decision) return
    setBusy(true); setError(null)
    try {
      await api.adminDecideApplication(slug, decision.appId, {
        status: decision.status,
        comment: comment || null,
      })
      setDecision(null); setComment('')
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
          <h1>Заявки</h1>
        </div>
        <Link to={`/admin/competitions`} className="btn">← К списку</Link>
      </div>

      <div className="adm-toolbar">
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
        >
          <option value="">все статусы</option>
          {Object.entries(STATUS_LABEL).map(([k, v]) => (
            <option key={k} value={k}>{v}</option>
          ))}
        </select>
        <button className="btn" onClick={load} disabled={loading}>Обновить</button>
      </div>

      {error && <div className="alert">{error}</div>}

      {loading ? (
        <p className="mono" style={{ color: 'var(--text-dim)' }}>загрузка…</p>
      ) : items.length === 0 ? (
        <div className="empty-state"><p>Заявок нет.</p></div>
      ) : (
        <div className="adm-table-wrap">
          <table className="adm-table">
            <thead>
              <tr>
                <th>#</th>
                <th>пользователь</th>
                <th>team_id</th>
                <th>статус</th>
                <th>подана</th>
                <th>мотивация</th>
                <th>действия</th>
              </tr>
            </thead>
            <tbody>
              {items.map((a) => (
                <tr key={a.id}>
                  <td className="mono">#{a.id}</td>
                  <td><strong>{a.username}</strong></td>
                  <td className="mono">{a.team_id ?? '—'}</td>
                  <td>
                    <span className="adm-badge">{STATUS_LABEL[a.status] || a.status}</span>
                  </td>
                  <td className="mono" style={{ fontSize: 11 }}>
                    {new Date(a.applied_at).toLocaleString('ru-RU')}
                  </td>
                  <td style={{ maxWidth: 260, fontSize: 12, color: 'var(--text-dim)' }}>
                    {a.motivation || a.comment || '—'}
                  </td>
                  <td>
                    <div className="actions">
                      <button
                        className="adm-btn-mini"
                        disabled={busy || a.status === 'approved'}
                        onClick={() => { setDecision({ appId: a.id, status: 'approved' }); setComment('') }}
                      >
                        Одобрить
                      </button>
                      <button
                        className="adm-btn-mini danger"
                        disabled={busy || a.status === 'rejected'}
                        onClick={() => { setDecision({ appId: a.id, status: 'rejected' }); setComment('') }}
                      >
                        Отклонить
                      </button>
                      <button
                        className="adm-btn-mini"
                        disabled={busy || a.status === 'waitlist'}
                        onClick={() => { setDecision({ appId: a.id, status: 'waitlist' }); setComment('') }}
                      >
                        В лист ожидания
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {decision && (
        <div className="adm-card" style={{ marginTop: 20 }}>
          <h3>
            {decision.status === 'approved' && 'Одобрить заявку'}
            {decision.status === 'rejected' && 'Отклонить заявку'}
            {decision.status === 'waitlist' && 'Перевести в лист ожидания'}
          </h3>
          <div className="wiz-field">
            <label>Комментарий (опционально)</label>
            <input value={comment} onChange={(e) => setComment(e.target.value)} />
          </div>
          <div style={{ display: 'flex', gap: 10 }}>
            <button className="btn btn-primary" disabled={busy} onClick={submitDecision}>
              Подтвердить
            </button>
            <button className="btn" onClick={() => { setDecision(null); setComment('') }}>
              Отмена
            </button>
          </div>
        </div>
      )}
    </div>
  )
}