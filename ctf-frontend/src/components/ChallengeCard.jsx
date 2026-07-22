import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import './ChallengeCard.css'

const DIFFICULTY_LABEL = {
  easy: 'лёгкий',
  medium: 'средний',
  hard: 'сложный',
}

function formatCountdown(expiresAt) {
  const diff = new Date(expiresAt).getTime() - Date.now()
  if (diff <= 0) return '00:00'
  const totalSeconds = Math.floor(diff / 1000)
  const minutes = String(Math.floor(totalSeconds / 60)).padStart(2, '0')
  const seconds = String(totalSeconds % 60).padStart(2, '0')
  return `${minutes}:${seconds}`
}

export default function ChallengeCard({ challenge, onSolved }) {
  const [expanded, setExpanded] = useState(false)
  const [instance, setInstance] = useState(null)
  const [flag, setFlag] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)
  const [countdown, setCountdown] = useState(null)
  const timerRef = useRef(null)

  useEffect(() => {
    if (!instance) {
      setCountdown(null)
      return
    }
    setCountdown(formatCountdown(instance.expires_at))
    timerRef.current = setInterval(() => {
      setCountdown(formatCountdown(instance.expires_at))
    }, 1000)
    return () => clearInterval(timerRef.current)
  }, [instance])

  async function handleStart() {
    setError(null)
    setBusy(true)
    try {
      const data = await api.startChallenge(challenge.slug)
      setInstance(data)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось запустить инстанс')
    } finally {
      setBusy(false)
    }
  }

  async function handleStop() {
    setError(null)
    setBusy(true)
    try {
      await api.stopChallenge(challenge.slug)
      setInstance(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось остановить инстанс')
    } finally {
      setBusy(false)
    }
  }

  async function handleSubmit(e) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    setResult(null)
    try {
      const data = await api.submitFlag(challenge.slug, flag)
      setResult(data)
      if (data.correct) {
        setFlag('')
        onSolved?.(challenge.id)
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось проверить флаг')
    } finally {
      setBusy(false)
    }
  }

  return (
    <article className={`case-card${challenge.solved ? ' solved' : ''}${expanded ? ' open' : ''}`}>
      <button className="case-card-head" onClick={() => setExpanded((v) => !v)}>
        <span className={`diff-stamp diff-${challenge.difficulty}`}>
          {DIFFICULTY_LABEL[challenge.difficulty] || challenge.difficulty}
        </span>

        <div className="case-card-title">
          <h3>{challenge.title}</h3>
          <span className="mono case-card-meta">
            {challenge.category} · {challenge.points} pts · #{challenge.slug}
          </span>
        </div>

        <div className="case-card-status">
          {challenge.solved && <span className="badge solved-badge">решено</span>}
          {instance && <span className="live-dot" title="Инстанс запущен" />}
          <span className={`chevron${expanded ? ' up' : ''}`}>⌄</span>
        </div>
      </button>

      {expanded && (
        <div className="case-card-body">
          <p className="case-card-desc">{challenge.description}</p>

          {error && <div className="alert">{error}</div>}
          {result && (
            <div className={`alert ${result.correct ? 'alert-success' : ''}`}>
              {result.message}
              {result.correct && result.points_awarded ? ` (+${result.points_awarded} pts)` : ''}
            </div>
          )}

          {result && result.correct && (
            <div style={{ marginBottom: 16 }}>
              <Link to={`/writeups/${challenge.slug}`} className="btn">
                📖 Посмотреть решение
              </Link>
            </div>
          )}

          <div className="instance-controls">
            {!instance ? (
              <button className="btn btn-primary" onClick={handleStart} disabled={busy}>
                {busy ? 'Запуск…' : 'Запустить инстанс'}
              </button>
            ) : (
              <>
                <div className="instance-info">
                  <a
                    className="mono instance-link"
                    href={instance.url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {instance.url} ↗
                  </a>
                  <span className="mono instance-ttl">истекает через {countdown}</span>
                </div>
                <button className="btn btn-danger" onClick={handleStop} disabled={busy}>
                  Остановить
                </button>
              </>
            )}
          </div>

          <form className="flag-form" onSubmit={handleSubmit}>
            <input
              className="mono"
              placeholder="flag{...}"
              value={flag}
              onChange={(e) => setFlag(e.target.value)}
              disabled={busy || challenge.solved}
              required
            />
            <button className="btn" type="submit" disabled={busy || challenge.solved}>
              {challenge.solved ? 'Решено' : 'Отправить'}
            </button>
          </form>
        </div>
      )}
    </article>
  )
}

