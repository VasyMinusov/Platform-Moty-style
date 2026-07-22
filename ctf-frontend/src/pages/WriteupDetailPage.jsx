import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import './WriteupsPage.css'

export default function WriteupDetailPage() {
  const { slug } = useParams()
  const [writeup, setWriteup] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    load()
  }, [slug])

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const data = await api.getWriteup(slug)
      setWriteup(data)
    } catch (err) {
      if (err.status === 403) {
        setError('Вы ещё не решили это задание или оно не существует.')
      } else {
        setError(err instanceof ApiError ? err.message : 'Ошибка загрузки')
      }
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

  if (!writeup) {
    return <div className="alert">Запись не найдена</div>
  }

  // Парсим JSON-содержимое
  let content
  try {
    content = JSON.parse(writeup.content_json)
  } catch {
    content = { description: writeup.content_json, steps: [] }
  }

  return (
    <div>
      <div className="page-head">
        <div>
          <span className="eyebrow">решение</span>
          <h1>{writeup.title}</h1>
          <p style={{ color: 'var(--text-dim)', fontSize: 14 }}>
            задание: {writeup.challenge_slug}
          </p>
        </div>
        <Link to="/writeups" className="btn">← к списку</Link>
      </div>

      {content.description && (
        <div
          style={{
            marginBottom: 24,
            background: 'var(--panel-alt)',
            padding: 16,
            borderRadius: 'var(--radius-sm)',
          }}
        >
          <p style={{ margin: 0 }}>{content.description}</p>
        </div>
      )}

      {content.steps && content.steps.length > 0 && (
        <div className="step-list">
          {content.steps.map((step) => (
            <div
              key={step.step || step.title}
              className="step-item"
              data-step={`Шаг ${step.step || '?'}`}
            >
              <h4>{step.title}</h4>
              <p>{step.detail}</p>
              {step.command && (
                <div className="step-command">{step.command}</div>
              )}
            </div>
          ))}
        </div>
      )}

      {content.flag && (
        <div
          style={{
            marginTop: 24,
            padding: 12,
            background: 'var(--success-soft)',
            border: '1px solid var(--success)',
            borderRadius: 'var(--radius-sm)',
          }}
        >
          <span className="mono" style={{ color: 'var(--success)' }}>
            Флаг: {content.flag}
          </span>
        </div>
      )}
    </div>
  )
}

