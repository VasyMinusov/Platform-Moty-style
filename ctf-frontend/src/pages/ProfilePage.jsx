import { useEffect, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import { api, ApiError } from '../api/client'
import { decodeJwt } from '../api/jwt'
import './ProfilePage.css'

export default function ProfilePage() {
  const { username, token } = useAuth()
  const [challenges, setChallenges] = useState([])
  const [me, setMe] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    load()
  }, [])

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const [data, meData] = await Promise.all([api.listChallenges(), api.me()])
      setChallenges(data)
      setMe(meData)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось загрузить данные')
    } finally {
      setLoading(false)
    }
  }

  const solved = challenges.filter((c) => c.solved)
  const totalPoints = solved.reduce((sum, c) => sum + c.points, 0)
  const payload = token ? decodeJwt(token) : null
  const expires = payload?.exp ? new Date(payload.exp * 1000) : null

  return (
    <div>
      <div className="page-head">
        <div>
          <span className="eyebrow">личное дело</span>
          <h1>{username}</h1>
          {me?.status && <span className="profile-status mono">#{me.status}</span>}
        </div>
      </div>

      {error && <div className="alert">{error}</div>}

      <div className="profile-stats">
        <div className="stat-card">
          <span className="eyebrow">очки</span>
          <span className="stat-value mono">{loading ? '—' : totalPoints}</span>
        </div>
        <div className="stat-card">
          <span className="eyebrow">решено заданий</span>
          <span className="stat-value mono">
            {loading ? '—' : `${solved.length} / ${challenges.length}`}
          </span>
        </div>
        <div className="stat-card">
          <span className="eyebrow">сессия истекает</span>
          <span className="stat-value mono" style={{ fontSize: 15 }}>
            {expires ? expires.toLocaleString('ru-RU') : '—'}
          </span>
        </div>
      </div>

      <h2 className="section-title">Решённые задания</h2>
      {loading ? (
        <p className="mono" style={{ color: 'var(--text-dim)' }}>
          загрузка…
        </p>
      ) : solved.length === 0 ? (
        <div className="empty-state">
          <p>Пока ни одного решённого задания. Начните с раздела «Задания».</p>
        </div>
      ) : (
        <ul className="solved-list">
          {solved.map((c) => (
            <li key={c.id} className="solved-item">
              <span className="mono solved-slug">#{c.slug}</span>
              <span className="solved-title">{c.title}</span>
              <span className="mono solved-points">+{c.points}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}


