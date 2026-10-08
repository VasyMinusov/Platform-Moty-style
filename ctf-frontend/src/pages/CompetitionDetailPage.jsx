import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, ApiError, downloadAndSave } from '../api/client'
import { useAuth } from '../context/AuthContext'
import { useNotifications } from '../context/NotificationsContext'
import { useCompetitionStream } from '../api/competitionsStream'
import './CompetitionDetailPage.css'

const TABS = [
  ['overview', 'Обзор'],
  ['challenges', 'Задания'],
  ['leaderboard', 'Leaderboard'],
  ['rules', 'Правила'],
  ['me', 'Моя заявка'],
]

function formatDt(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatSize(bytes) {
  if (bytes === null || bytes === undefined) return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`
}

export default function CompetitionDetailPage() {
  const { slug } = useParams()
  const { token, role } = useAuth()
  const { push } = useNotifications()

  const [tab, setTab] = useState('overview')
  const [comp, setComp] = useState(null)
  const [myApp, setMyApp] = useState(null)
  const [myTeam, setMyTeam] = useState(null)
  const [invitations, setInvitations] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const isStaff = role === 'admin' || role === 'moderator'

  useEffect(() => {
    load()
  }, [slug])

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const c = await api.getCompetition(slug)
      setComp(c)
      const [app, team, invs] = await Promise.all([
        api.getMyApplication(slug).catch(() => null),
        api.getMyTeam(slug).catch(() => null),
        api.getMyInvitations(slug).catch(() => []),
      ])
      setMyApp(app)
      setMyTeam(team)
      setInvitations(invs || [])
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : 'Не удалось загрузить соревнование',
      )
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return <p className="mono" style={{ color: 'var(--text-dim)' }}>загрузка…</p>
  }
  if (error) {
    return (
      <div>
        <div className="alert">{error}</div>
        <Link to="/competitions" className="btn">← К списку</Link>
      </div>
    )
  }
  if (!comp) return null

  return (
    <div>
      <div className="page-head">
        <div>
          <span className="eyebrow mono">{comp.slug}</span>
          <h1>{comp.title}</h1>
          <p className="comp-detail-summary">{comp.summary}</p>
        </div>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <Link to="/competitions" className="btn">← К списку</Link>
          {isStaff && (
            <Link
              to={`/admin/competitions/${comp.slug}/edit`}
              className="btn btn-primary"
            >
              Редактировать
            </Link>
          )}
        </div>
      </div>

      <div className="comp-meta mono">
        <span className={`comp-status comp-status-${comp.status}`}>
          {comp.status}
        </span>
        <span>·</span>
        <span>
          {comp.mode === 'individual'
            ? 'индивидуальное'
            : comp.mode === 'team'
              ? 'командное'
              : 'индивид.+команды'}
        </span>
        <span>·</span>
        <span>
          регистрация: {formatDt(comp.registration_opens_at)} →{' '}
          {formatDt(comp.registration_closes_at)}
        </span>
        <span>·</span>
        <span>старт: {formatDt(comp.starts_at)}</span>
        <span>·</span>
        <span>финиш: {formatDt(comp.ends_at)}</span>
      </div>

      <div className="comp-tabs">
        {TABS.map(([key, label]) => (
          <button
            key={key}
            className={`comp-tab${tab === key ? ' active' : ''}`}
            onClick={() => setTab(key)}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === 'overview' && (
        <OverviewTab
          comp={comp}
          myApp={myApp}
          myTeam={myTeam}
          onReload={load}
          push={push}
        />
      )}
      {tab === 'challenges' && <ChallengesTab slug={slug} push={push} />}
      {tab === 'leaderboard' && (
        <LeaderboardTab slug={slug} token={token} push={push} />
      )}
      {tab === 'rules' && (
        <div className="comp-markdown">
          <pre>{comp.rules_md || 'Правила не заданы.'}</pre>
        </div>
      )}
      {tab === 'me' && (
        <MyApplicationTab
          comp={comp}
          myApp={myApp}
          myTeam={myTeam}
          invitations={invitations}
          onReload={load}
          push={push}
        />
      )}
    </div>
  )
}

// ── Overview ────────────────────────────────────────────────────────

function OverviewTab({ comp, myApp, myTeam, onReload, push }) {
  const { isAuthenticated } = useAuth()
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  const canApply =
    isAuthenticated &&
    comp.status === 'registration_open' &&
    (!myApp || ['withdrawn', 'rejected'].includes(myApp.status)) &&
    !myTeam &&
    comp.mode !== 'team'

  async function apply() {
    setBusy(true)
    setErr(null)
    try {
      await api.applyToCompetition(comp.slug, {})
      push?.({
        type: 'application.created',
        title: 'Заявка подана',
        message: comp.title,
        level: 'success',
        link: `/competitions/${comp.slug}`,
      })
      await onReload()
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : 'Ошибка')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="comp-overview">
      {err && <div className="alert">{err}</div>}

      <div className="comp-markdown">
        <pre>{comp.description_md || 'Описание не задано.'}</pre>
      </div>

      {canApply && (
        <div className="comp-cta">
          <p>Регистрация открыта. Подайте заявку на участие.</p>
          <button className="btn btn-primary" disabled={busy} onClick={apply}>
            {busy ? 'Отправка…' : 'Подать заявку'}
          </button>
        </div>
      )}

      {!isAuthenticated && (
        <div className="comp-cta">
          <p>Войдите, чтобы подать заявку на участие.</p>
          <Link to="/login" className="btn btn-primary">Войти</Link>
        </div>
      )}

      {myApp && (
        <div className="comp-cta">
          <p>
            Статус вашей заявки: <strong>{myApp.status}</strong>
          </p>
        </div>
      )}
    </div>
  )
}

// ── Challenges ──────────────────────────────────────────────────────

function ChallengesTab({ slug, push }) {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    load()
  }, [slug])

  async function load() {
    setLoading(true)
    setError(null)
    try {
      setItems(await api.listCompetitionChallenges(slug))
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : 'Не удалось загрузить задания',
      )
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return <p className="mono" style={{ color: 'var(--text-dim)' }}>загрузка…</p>
  }
  if (error) return <div className="alert">{error}</div>
  if (items.length === 0) {
    return (
      <div className="empty-state">
        <p>Задания ещё не опубликованы.</p>
      </div>
    )
  }

  return (
    <div className="challenge-list">
      {items.map((ch) => (
        <CompetitionChallengeCard
          key={ch.id}
          slug={slug}
          challenge={ch}
          onSolved={load}
          push={push}
        />
      ))}
    </div>
  )
}

function CompetitionChallengeCard({ slug, challenge, onSolved, push }) {
  const [expanded, setExpanded] = useState(false)
  const [instance, setInstance] = useState(null)
  const [flag, setFlag] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)
  const [purchased, setPurchased] = useState([])
  const [downloading, setDownloading] = useState(null)

  useEffect(() => {
    if (expanded && challenge.hints_json?.length) {
      api
        .listPurchasedHints(slug, challenge.slug)
        .then(setPurchased)
        .catch(() => setPurchased([]))
    }
  }, [expanded, slug, challenge.slug, challenge.hints_json])

  async function start() {
    setError(null)
    setBusy(true)
    try {
      const data = await api.startCompetitionChallenge(slug, challenge.slug)
      setInstance(data)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось запустить')
    } finally {
      setBusy(false)
    }
  }

  async function stop() {
    setError(null)
    setBusy(true)
    try {
      await api.stopCompetitionChallenge(slug, challenge.slug)
      setInstance(null)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось остановить')
    } finally {
      setBusy(false)
    }
  }

  async function submit(e) {
    e.preventDefault()
    setError(null)
    setResult(null)
    setBusy(true)
    try {
      const data = await api.submitCompetitionFlag(slug, challenge.slug, flag)
      setResult(data)
      if (data.correct) {
        push?.({
          type: 'challenge.solved',
          title: data.is_first_blood ? 'First blood!' : 'Задание решено',
          message: `${challenge.title} · +${data.points_awarded} pts`,
          level: data.is_first_blood ? 'warning' : 'success',
          link: `/competitions/${slug}`,
        })
        setFlag('')
        setInstance(null)
        onSolved?.()
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Ошибка проверки')
    } finally {
      setBusy(false)
    }
  }

  async function buyHint(idx) {
    setError(null)
    setBusy(true)
    try {
      const h = await api.buyHint(slug, challenge.slug, idx)
      setPurchased((p) => [...p, h])
      push?.({
        type: 'hint.purchased',
        title: 'Подсказка куплена',
        message: `${challenge.title} · −${h.cost_paid} pts`,
        level: 'warning',
      })
    } catch (e) {
      setError(
        e instanceof ApiError ? e.message : 'Не удалось купить подсказку',
      )
    } finally {
      setBusy(false)
    }
  }

  async function downloadFile(f) {
    setError(null)
    setDownloading(f.id)
    try {
      await downloadAndSave(
        `/competitions/${slug}/challenges/${challenge.slug}/files/${f.id}`,
        f.filename,
      )
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось скачать файл')
    } finally {
      setDownloading(null)
    }
  }

  const hintsArr = challenge.hints_json || []
  const purchasedIdx = new Set(purchased.map((p) => p.hint_index))
  const filesArr = challenge.files || []

  return (
    <article
      className={`case-card${challenge.solved ? ' solved' : ''}${expanded ? ' open' : ''}`}
    >
      <button className="case-card-head" onClick={() => setExpanded((v) => !v)}>
        <span className={`diff-stamp diff-${challenge.difficulty}`}>
          {challenge.difficulty}
        </span>
        <div className="case-card-title">
          <h3>{challenge.title}</h3>
          <span className="mono case-card-meta">
            {challenge.type} · {challenge.category} · {challenge.points} pts · #
            {challenge.slug}
          </span>
        </div>
        <div className="case-card-status">
          {challenge.solved && <span className="badge solved-badge">решено</span>}
          {instance && <span className="live-dot" />}
          <span className={`chevron${expanded ? ' up' : ''}`}>⌄</span>
        </div>
      </button>

      {expanded && (
        <div className="case-card-body">
          <p className="case-card-desc">{challenge.description_md}</p>

          {error && <div className="alert">{error}</div>}
          {result && (
            <div className={`alert ${result.correct ? 'alert-success' : ''}`}>
              {result.message}
              {result.correct && result.is_first_blood && ' · first blood!'}
            </div>
          )}

          {challenge.kind === 'docker' && (
            <div className="instance-controls">
              {!instance ? (
                <button
                  className="btn btn-primary"
                  onClick={start}
                  disabled={busy}
                >
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
                  </div>
                  <button
                    className="btn btn-danger"
                    onClick={stop}
                    disabled={busy}
                  >
                    Остановить
                  </button>
                </>
              )}
            </div>
          )}

          {challenge.kind === 'static' && filesArr.length === 0 && (
            <div className="instance-controls">
              <p
                className="mono"
                style={{ fontSize: 12, color: 'var(--text-dim)' }}
              >
                Статическое задание — файлы ещё не загружены.
              </p>
            </div>
          )}

          {filesArr.length > 0 && (
            <div className="challenge-files">
              <h4 className="eyebrow">Файлы</h4>
              <ul className="challenge-files-list">
                {filesArr.map((f) => (
                  <li key={f.id} className="challenge-file">
                    <span className="mono challenge-file-name">{f.filename}</span>
                    <span className="mono challenge-file-size">
                      {formatSize(f.size)}
                    </span>
                    <button
                      className="btn"
                      disabled={downloading === f.id}
                      onClick={() => downloadFile(f)}
                    >
                      {downloading === f.id ? 'Скачивание…' : 'Скачать'}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <form className="flag-form" onSubmit={submit}>
            <input
              className="mono"
              placeholder="flag{...}"
              value={flag}
              onChange={(e) => setFlag(e.target.value)}
              disabled={busy || challenge.solved}
              required
            />
            <button
              className="btn"
              type="submit"
              disabled={busy || challenge.solved}
            >
              {challenge.solved ? 'Решено' : 'Отправить'}
            </button>
          </form>

          {hintsArr.length > 0 && (
            <div className="hint-list">
              <h4 className="eyebrow">Подсказки</h4>
              {hintsArr.map((h, idx) => {
                const owned = purchasedIdx.has(idx)
                return (
                  <div key={idx} className={`hint-item${owned ? ' owned' : ''}`}>
                    <div className="hint-text">
                      {owned ? h.text : `Подсказка #${idx + 1} (${h.cost} pts)`}
                    </div>
                    {!owned && (
                      <button
                        className="btn"
                        disabled={busy}
                        onClick={() => buyHint(idx)}
                      >
                        Купить
                      </button>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}
    </article>
  )
}

// ── Leaderboard ─────────────────────────────────────────────────────

function LeaderboardTab({ slug, token, push }) {
  const [snapshot, setSnapshot] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    api
      .getLeaderboard(slug)
      .then((s) => setSnapshot(s))
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Ошибка'))
      .finally(() => setLoading(false))
  }, [slug])

  useCompetitionStream(slug, token, (event) => {
    if (event.type === 'leaderboard.snapshot') {
      api.getLeaderboard(slug).then(setSnapshot).catch(() => {})
    } else if (event.type === 'solve.created') {
      const d = event.data || {}
      push?.({
        type: 'solve.created',
        title: d.is_first_blood ? 'First blood!' : 'Новое решение',
        message: `${d.challenge_slug} · +${d.points ?? 0} pts`,
        level: d.is_first_blood ? 'warning' : 'info',
        link: `/competitions/${slug}`,
      })
      api.getLeaderboard(slug).then(setSnapshot).catch(() => {})
    }
  })

  if (loading) {
    return <p className="mono" style={{ color: 'var(--text-dim)' }}>загрузка…</p>
  }
  if (error) return <div className="alert">{error}</div>
  if (!snapshot) return null

  const rows = snapshot.mode === 'team' ? snapshot.teams : snapshot.individuals

  return (
    <div className="lb-wrap">
      {rows.length === 0 ? (
        <div className="empty-state">
          <p>Пока ни одного решения.</p>
        </div>
      ) : (
        <table className="lb-table">
          <thead>
            <tr>
              <th>#</th>
              <th>Участник</th>
              <th>Очки</th>
              <th>Решено</th>
              <th>Последнее</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td className="mono">{r.rank}</td>
                <td>
                  <strong>{r.name}</strong>
                  {r.is_team && r.members?.length > 0 && (
                    <div className="lb-members mono">{r.members.join(', ')}</div>
                  )}
                </td>
                <td className="mono lb-score">{r.score}</td>
                <td className="mono">{r.solves_count}</td>
                <td className="mono lb-time">
                  {r.last_solve_at
                    ? new Date(r.last_solve_at).toLocaleString('ru-RU')
                    : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

// ── My application ──────────────────────────────────────────────────

function MyApplicationTab({ comp, myApp, myTeam, invitations, onReload, push }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  async function withdraw() {
    if (!confirm('Отозвать заявку?')) return
    setBusy(true)
    setError(null)
    try {
      await api.withdrawFromCompetition(comp.slug)
      push?.({
        type: 'application.withdrawn',
        title: 'Заявка отозвана',
        message: comp.title,
        level: 'info',
      })
      await onReload()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Ошибка')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      {error && <div className="alert">{error}</div>}

      {comp.mode !== 'individual' && (
        <div className="me-section">
          <h3>Команда</h3>
          {myTeam ? (
            <TeamSummaryBlock comp={comp} team={myTeam} onReload={onReload} />
          ) : (
            <div>
              <p>У вас нет команды в этом соревновании.</p>
              <Link
                to={`/competitions/${comp.slug}/team`}
                className="btn btn-primary"
              >
                Создать / присоединиться
              </Link>
            </div>
          )}
        </div>
      )}

      {invitations.length > 0 && (
        <div className="me-section">
          <h3>Приглашения в команды</h3>
          <ul className="invites-list">
            {invitations.map((t) => (
              <li key={t.id} className="invite-item">
                <span>
                  {t.name} (капитан: {t.captain_username})
                </span>
                <div style={{ display: 'flex', gap: 8 }}>
                  <button
                    className="btn btn-primary"
                    onClick={async () => {
                      await api.acceptInvite(comp.slug, t.id)
                      push?.({
                        type: 'team.invite.accepted',
                        title: 'Вы приняли приглашение',
                        message: t.name,
                        level: 'success',
                      })
                      await onReload()
                    }}
                  >
                    Принять
                  </button>
                  <button
                    className="btn"
                    onClick={async () => {
                      await api.declineInvite(comp.slug, t.id)
                      push?.({
                        type: 'team.invite.declined',
                        title: 'Приглашение отклонено',
                        message: t.name,
                        level: 'info',
                      })
                      await onReload()
                    }}
                  >
                    Отклонить
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="me-section">
        <h3>Заявка</h3>
        {myApp ? (
          <div>
            <p>
              Статус: <strong>{myApp.status}</strong>
              {myApp.decision_comment && (
                <>
                  {' '}
                  — <em>{myApp.decision_comment}</em>
                </>
              )}
            </p>
            {['pending', 'waitlist', 'team_pending'].includes(myApp.status) && (
              <button className="btn btn-danger" disabled={busy} onClick={withdraw}>
                Отозвать
              </button>
            )}
          </div>
        ) : (
          <p>Заявка не подана.</p>
        )}
      </div>
    </div>
  )
}

function TeamSummaryBlock({ comp, team, onReload }) {
  return (
    <div>
      <p>
        <strong>{team.name}</strong> · статус: {team.status} · состав:{' '}
        {team.member_count}
      </p>
      {team.members?.length > 0 && (
        <ul className="team-members-list">
          {team.members.map((m) => (
            <li key={m.user_id}>
              <span className="mono">{m.username}</span> · {m.role} · {m.status}
            </li>
          ))}
        </ul>
      )}
      <Link to={`/competitions/${comp.slug}/team`} className="btn">
        Управление командой
      </Link>
    </div>
  )
}