import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import { useAuth } from '../context/AuthContext'
import './Lessons.css'

export default function LessonsListPage() {
  const { role } = useAuth()
  const canManageLessons = role === 'admin' || role === 'moderator'
  const navigate = useNavigate()
  const [lessons, setLessons] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    load()
  }, [])

  async function load() {
    setError(null)
    try {
      setLessons(await api.listLessons())
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось загрузить библиотеку')
    } finally {
      setLoading(false)
    }
  }

  async function handleDelete(slug) {
    if (!confirm(`Удалить занятие «${slug}»?`)) return
    try {
      await api.deleteLesson(slug)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Ошибка удаления')
    }
  }

  return (
    <div>
      <div className="page-head">
        <div>
          <span className="eyebrow">база знаний</span>
          <h1>Библиотека занятий</h1>
        </div>
        {canManageLessons && (
          <button className="btn btn-primary" onClick={() => navigate('/lessons/new')}>
            + Новое занятие
          </button>
        )}
      </div>

      {error && <div className="alert">{error}</div>}

      {loading ? (
        <p className="mono" style={{ color: 'var(--text-dim)' }}>загрузка…</p>
      ) : lessons.length === 0 ? (
        <div className="lessons-empty">
          <p>В библиотеке пока нет занятий.</p>
          {canManageLessons && (
            <button className="btn btn-primary" onClick={() => navigate('/lessons/new')}>
              Создать первое занятие
            </button>
          )}
        </div>
      ) : (
        <div className="admin-grid">
          {lessons.map((l) => (
            <div key={l.slug} className="lesson-card">
              <span className="eyebrow mono">{l.slug}</span>
              <h3>
                <Link to={`/lessons/${l.slug}`}>{l.title}</Link>
              </h3>
              {l.summary && <p className="lesson-summary">{l.summary}</p>}
              <span className="meta">
                {l.author_username ? `автор: ${l.author_username} · ` : ''}
                обновлено: {new Date(l.updated_at).toLocaleString('ru-RU')}
              </span>
              <div className="actions">
                <Link to={`/lessons/${l.slug}`} className="btn">Открыть</Link>
                {canManageLessons && (
                  <>
                    <Link to={`/lessons/${l.slug}/edit`} className="btn">Редактировать</Link>
                    <button className="btn btn-danger" onClick={() => handleDelete(l.slug)}>
                      Удалить
                    </button>
                  </>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
