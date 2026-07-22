import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import { useAuth } from '../context/AuthContext'
import { MarkdownView } from '../components/MarkdownView'
import './Lessons.css'

export default function LessonDetailPage() {
  const { slug } = useParams()
  const navigate = useNavigate()
  const { role } = useAuth()
  const canManageLessons = role === 'admin' || role === 'moderator'
  const [lesson, setLesson] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    api.getLesson(slug)
      .then(setLesson)
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Занятие не найдено'))
      .finally(() => setLoading(false))
  }, [slug])

  if (loading) {
    return <p className="mono" style={{ color: 'var(--text-dim)' }}>загрузка…</p>
  }

  if (error) {
    return (
      <div>
        <div className="alert">{error}</div>
        <Link to="/lessons" className="btn">← К библиотеке</Link>
      </div>
    )
  }

  return (
    <div className="lesson-detail">
      <div className="page-head">
        <div>
          <span className="eyebrow mono">{lesson.slug}</span>
          <h1>{lesson.title}</h1>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <button className="btn" onClick={() => navigate('/lessons')}>← К библиотеке</button>
          {canManageLessons && (
            <Link to={`/lessons/${lesson.slug}/edit`} className="btn btn-primary">
              Редактировать
            </Link>
          )}
        </div>
      </div>

      <span className="meta mono lesson-detail-meta">
        {lesson.author_username ? `автор: ${lesson.author_username} · ` : ''}
        обновлено: {new Date(lesson.updated_at).toLocaleString('ru-RU')}
      </span>

      <MarkdownView source={lesson.content_md} className="lesson-content" />
    </div>
  )
}
