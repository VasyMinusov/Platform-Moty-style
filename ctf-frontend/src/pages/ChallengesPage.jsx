import { useEffect, useMemo, useState } from 'react'
import { api, ApiError } from '../api/client'
import ChallengeCard from '../components/ChallengeCard'
import './ChallengesPage.css'

const ALL = 'all'

export default function ChallengesPage() {
  const [challenges, setChallenges] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [category, setCategory] = useState(ALL)
  const [status, setStatus] = useState(ALL)

  useEffect(() => {
    load()
  }, [])

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const data = await api.listChallenges()
      setChallenges(data)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось загрузить задания')
    } finally {
      setLoading(false)
    }
  }

  function markSolved(id) {
    setChallenges((prev) => prev.map((c) => (c.id === id ? { ...c, solved: true } : c)))
  }

  const categories = useMemo(
    () => [ALL, ...new Set(challenges.map((c) => c.category))],
    [challenges]
  )

  const filtered = useMemo(
    () =>
      challenges.filter((c) => {
        if (category !== ALL && c.category !== category) return false
        if (status === 'solved' && !c.solved) return false
        if (status === 'open' && c.solved) return false
        return true
      }),
    [challenges, category, status]
  )

  const solvedCount = challenges.filter((c) => c.solved).length

  return (
    <div>
      <div className="page-head">
        <div>
          <span className="eyebrow">реестр заданий</span>
          <h1>Задания</h1>
        </div>
        <div className="progress-tag mono">
          решено {solvedCount} / {challenges.length}
        </div>
      </div>

      <div className="filters">
        <div className="filter-group">
          {categories.map((c) => (
            <button
              key={c}
              className={`filter-chip${category === c ? ' active' : ''}`}
              onClick={() => setCategory(c)}
            >
              {c === ALL ? 'все категории' : c}
            </button>
          ))}
        </div>
        <div className="filter-group">
          {[
            [ALL, 'все'],
            ['open', 'не решено'],
            ['solved', 'решено'],
          ].map(([value, label]) => (
            <button
              key={value}
              className={`filter-chip${status === value ? ' active' : ''}`}
              onClick={() => setStatus(value)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {error && <div className="alert">{error}</div>}

      {loading ? (
        <p className="mono" style={{ color: 'var(--text-dim)' }}>
          загрузка реестра…
        </p>
      ) : filtered.length === 0 ? (
        <div className="empty-state">
          <p>По выбранным фильтрам заданий не найдено.</p>
        </div>
      ) : (
        <div className="case-list">
          {filtered.map((challenge) => (
            <ChallengeCard key={challenge.id} challenge={challenge} onSolved={markSolved} />
          ))}
        </div>
      )}
    </div>
  )
}


