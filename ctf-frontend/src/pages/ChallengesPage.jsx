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

  // Слаг → данные инстанса. Заполняется из /challenges/instances/running.
  // Карточка получает initialInstance и сразу показывает «Запущено»,
  // если контейнер уже работает на бэке.
  const [runningBySlug, setRunningBySlug] = useState({})

  useEffect(() => {
    load()
  }, [])

  async function load() {
    setLoading(true)
    setError(null)
    try {
      // Два запроса параллельно. Список инстансов — best-effort:
      // если он упал, страница всё равно должна показать задания.
      const [challengesData, instancesData] = await Promise.all([
        api.listChallenges(),
        api.listRunningInstances().catch(() => []),
      ])

      setChallenges(challengesData)

      const map = {}
      for (const inst of instancesData) {
        map[inst.challenge_slug] = {
          url: inst.url,
          expires_at: inst.expires_at,
        }
      }
      setRunningBySlug(map)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось загрузить задания')
    } finally {
      setLoading(false)
    }
  }

  function markSolved(id) {
    setChallenges((prev) => prev.map((c) => (c.id === id ? { ...c, solved: true } : c)))
  }

  // Обновить локальную карту после start/stop в карточке.
  // Вызывается из ChallengeCard через onInstanceStateChange.
  function handleInstanceStateChange(slug, instance) {
    setRunningBySlug((prev) => {
      const next = { ...prev }
      if (instance) {
        next[slug] = {
          url: instance.url,
          expires_at: instance.expires_at,
        }
      } else {
        delete next[slug]
      }
      return next
    })
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
            <ChallengeCard
              key={challenge.id}
              challenge={challenge}
              initialInstance={runningBySlug[challenge.slug] || null}
              onSolved={markSolved}
              onInstanceStateChange={handleInstanceStateChange}
            />
          ))}
        </div>
      )}
    </div>
  )
}