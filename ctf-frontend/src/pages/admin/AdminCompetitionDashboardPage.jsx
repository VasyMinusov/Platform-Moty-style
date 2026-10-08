import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import './AdminCompetitions.css'

export default function AdminCompetitionDashboardPage() {
  const { slug } = useParams()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [adjustUser, setAdjustUser] = useState('')
  const [adjustTeam, setAdjustTeam] = useState('')
  const [adjustDelta, setAdjustDelta] = useState('')
  const [adjustComment, setAdjustComment] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => { load() }, [slug])

  async function load() {
    setLoading(true); setError(null)
    try {
      setData(await api.adminGetDashboard(slug))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Ошибка')
    } finally { setLoading(false) }
  }

  async function adjust() {
    setBusy(true); setError(null)
    try {
      const payload = {
        delta: Number(adjustDelta) || 0,
        comment: adjustComment || null,
      }
      if (adjustUser) payload.user_id = Number(adjustUser)
      else if (adjustTeam) payload.team_id = Number(adjustTeam)
      else throw new ApiError('Укажите user_id или team_id', 0, null)
      const r = await api.adminScoreAdjust(slug, payload)
      alert(`Очки начислены. Итого: ${r.total}`)
      setAdjustUser(''); setAdjustTeam(''); setAdjustDelta(''); setAdjustComment('')
      await load()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Ошибка')
    } finally { setBusy(false) }
  }

  if (loading) return <p className="mono" style={{ color: 'var(--text-dim)' }}>загрузка…</p>
  if (error && !data) return <div className="alert">{error}</div>
  if (!data) return null

  const maxTimeline = Math.max(1, ...data.solves_timeline.map((p) => p.count))

  return (
    <div>
      <div className="page-head">
        <div>
          <span className="eyebrow mono">{slug}</span>
          <h1>Дашборд</h1>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <button className="btn" onClick={load}>Обновить</button>
          <Link to={`/admin/competitions`} className="btn">← К списку</Link>
        </div>
      </div>

      {error && <div className="alert">{error}</div>}

      <div className="dash-grid">
        <div className="dash-stat">
          <span className="value">{data.solves.total || 0}</span>
          <span className="label">решений</span>
        </div>
        <div className="dash-stat">
          <span className="value">{data.solves.unique_users || 0}</span>
          <span className="label">уникальных участников</span>
        </div>
        <div className="dash-stat">
          <span className="value">{data.solves.unique_teams || 0}</span>
          <span className="label">команд</span>
        </div>
        <div className="dash-stat">
          <span className="value">{data.participants.approved || 0}</span>
          <span className="label">одобрено заявок</span>
        </div>
        <div className="dash-stat">
          <span className="value">{data.participants.pending || 0}</span>
          <span className="label">ожидают</span>
        </div>
        <div className="dash-stat">
          <span className="value">{data.challenges.enabled || 0}/{data.challenges.total || 0}</span>
          <span className="label">заданий активно</span>
        </div>
      </div>

      <div className="dash-panel">
        <h3>Решения по часам</h3>
        {data.solves_timeline.length === 0 ? (
          <p className="mono" style={{ color: 'var(--text-faint)' }}>нет данных</p>
        ) : (
          <div className="dash-bars">
            {data.solves_timeline.map((p, i) => (
              <div
                key={i}
                className="dash-bar"
                style={{ height: `${(p.count / maxTimeline) * 100}%` }}
                title={`${new Date(p.t).toLocaleString('ru-RU')}: ${p.count}`}
              />
            ))}
          </div>
        )}
      </div>

      <div className="dash-panel">
        <h3>First bloods</h3>
        {data.first_bloods.length === 0 ? (
          <p className="mono" style={{ color: 'var(--text-faint)' }}>пока нет</p>
        ) : (
          <ul style={{ paddingLeft: 20, fontSize: 13, color: 'var(--text-dim)' }}>
            {data.first_bloods.map((fb, i) => (
              <li key={i}>
                <span className="mono" style={{ color: 'var(--accent)' }}>{fb.challenge}</span>
                {' — '}<strong>{fb.owner}</strong>
                {' · '}{new Date(fb.at).toLocaleString('ru-RU')}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="dash-panel">
        <h3>Топ решателей</h3>
        <table className="adm-table">
          <thead>
            <tr><th>#</th><th>username</th><th>solves</th></tr>
          </thead>
          <tbody>
            {data.top_solvers.map((s, i) => (
              <tr key={s.user_id}>
                <td className="mono">{i + 1}</td>
                <td>{s.username}</td>
                <td className="mono">{s.solves}</td>
              </tr>
            ))}
            {data.top_solvers.length === 0 && (
              <tr><td colSpan={3} className="mono" style={{ color: 'var(--text-faint)' }}>нет данных</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="dash-panel">
        <h3>Активность по категориям</h3>
        <table className="adm-table">
          <thead><tr><th>категория</th><th>решений</th></tr></thead>
          <tbody>
            {data.category_activity.map((c) => (
              <tr key={c.category}>
                <td className="mono">{c.category}</td>
                <td className="mono">{c.solves}</td>
              </tr>
            ))}
            {data.category_activity.length === 0 && (
              <tr><td colSpan={2} className="mono" style={{ color: 'var(--text-faint)' }}>нет данных</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {data.anomalies.length > 0 && (
        <div className="dash-panel">
          <h3>Аномалии (не блокируют автоматически)</h3>
          {data.anomalies.map((a, i) => (
            <div key={i} className="dash-anomaly">
              <span className="type">{a.type}</span>
              <span className="mono">{JSON.stringify(a)}</span>
            </div>
          ))}
        </div>
      )}

      <div className="dash-panel">
        <h3>Ручная корректировка очков</h3>
        <div className="wiz-row-3">
          <div className="wiz-field">
            <label>user_id</label>
            <input value={adjustUser} onChange={(e) => setAdjustUser(e.target.value)} />
          </div>
          <div className="wiz-field">
            <label>team_id</label>
            <input value={adjustTeam} onChange={(e) => setAdjustTeam(e.target.value)} />
          </div>
          <div className="wiz-field">
            <label>Δ очков</label>
            <input
              type="number"
              value={adjustDelta}
              onChange={(e) => setAdjustDelta(e.target.value)}
            />
          </div>
        </div>
        <div className="wiz-field">
          <label>Комментарий</label>
          <input value={adjustComment} onChange={(e) => setAdjustComment(e.target.value)} />
        </div>
        <button className="btn btn-primary" disabled={busy} onClick={adjust}>
          Применить
        </button>
        <p className="mono" style={{ fontSize: 11, color: 'var(--text-faint)', marginTop: 8 }}>
          Укажите ровно одно: user_id или team_id.
        </p>
      </div>
    </div>
  )
}