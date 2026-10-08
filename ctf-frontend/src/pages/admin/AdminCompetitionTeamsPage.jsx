import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import './AdminCompetitions.css'

export default function AdminCompetitionTeamsPage() {
  const { slug } = useParams()
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => { load() }, [slug])

  async function load() {
    setLoading(true); setError(null)
    try {
      setItems(await api.adminListTeams(slug))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Ошибка')
    } finally { setLoading(false) }
  }

  return (
    <div>
      <div className="page-head">
        <div>
          <span className="eyebrow mono">{slug}</span>
          <h1>Команды</h1>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <button className="btn" onClick={load}>Обновить</button>
          <Link to={`/admin/competitions`} className="btn">← К списку</Link>
        </div>
      </div>

      {error && <div className="alert">{error}</div>}

      {loading ? (
        <p className="mono" style={{ color: 'var(--text-dim)' }}>загрузка…</p>
      ) : items.length === 0 ? (
        <div className="empty-state"><p>Команд нет.</p></div>
      ) : (
        <div className="adm-table-wrap">
          <table className="adm-table">
            <thead>
              <tr>
                <th>#</th>
                <th>название</th>
                <th>капитан</th>
                <th>статус</th>
                <th>состав</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map((t) => (
                <tr key={t.id}>
                  <td className="mono">#{t.id}</td>
                  <td>{t.name}</td>
                  <td className="mono">{t.captain_username}</td>
                  <td><span className="adm-badge">{t.status}</span></td>
                  <td className="mono">{t.member_count}</td>
                  <td>
                    <Link to={`/competitions/${slug}/teams/${t.id}`} className="adm-btn-mini">
                      Открыть
                    </Link>
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