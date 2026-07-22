import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import './WriteupsPage.css'

export default function WriteupsListPage() {
  const [writeups, setWriteups] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    load()
  }, [])

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const data = await api.listWriteups()
      setWriteups(data)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Ошибка загрузки')
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return <p className="mono" style={{ color: 'var(--text-dim)' }}>загрузка…</p>
  }

  if (error) {
    return <div className="alert">{error}</div>
  }

  return (
    <div>
      <div className="page-head">
        <div>
          <span className="eyebrow">база знаний</span>
          <h1>Write‑ups</h1>
        </div>
      </div>

      {writeups.length === 0 ? (
        <div className="writeups-empty">
          <p>У вас пока нет доступа ни к одному решению. Решите задание – и оно появится здесь.</p>
        </div>
      ) : (
        <div className="admin-grid">
          {writeups.map((w) => (
            <Link
              to={`/writeups/${w.challenge_slug}`}
              key={w.challenge_slug}
              className="writeup-card"
              style={{ textDecoration: 'none' }}
            >
              <span className="eyebrow mono">{w.challenge_slug}</span>
              <h3>{w.title}</h3>
              <span className="meta">
                обновлено: {new Date(w.updated_at).toLocaleString('ru-RU')}
              </span>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}

