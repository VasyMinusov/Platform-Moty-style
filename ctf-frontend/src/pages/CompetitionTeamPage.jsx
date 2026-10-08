import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import { useNotifications } from '../context/NotificationsContext'
import './CompetitionTeamPage.css'

export default function CompetitionTeamPage() {
  const { slug } = useParams()
  const navigate = useNavigate()
  const { push } = useNotifications()

  const [comp, setComp] = useState(null)
  const [team, setTeam] = useState(null)
  const [invitations, setInvitations] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const [newTeamName, setNewTeamName] = useState('')
  const [inviteUsername, setInviteUsername] = useState('')
  const [joinCode, setJoinCode] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => { load() }, [slug])

  async function load() {
    setLoading(true); setError(null)
    try {
      const c = await api.getCompetition(slug)
      setComp(c)
      const [t, invs] = await Promise.all([
        api.getMyTeam(slug).catch(() => null),
        api.getMyInvitations(slug).catch(() => []),
      ])
      setTeam(t)
      setInvitations(invs || [])
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Ошибка загрузки')
    } finally {
      setLoading(false)
    }
  }

  async function run(fn, onSuccess) {
    setBusy(true); setError(null)
    try {
      await fn()
      await load()
      if (onSuccess) onSuccess()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Ошибка')
    } finally {
      setBusy(false)
    }
  }

  if (loading) return <p className="mono" style={{ color: 'var(--text-dim)' }}>загрузка…</p>
  if (error && !comp) return <div className="alert">{error}</div>

  return (
    <div>
      <div className="page-head">
        <div>
          <span className="eyebrow mono">{slug}</span>
          <h1>Команда</h1>
        </div>
        <Link to={`/competitions/${slug}`} className="btn">← К соревнованию</Link>
      </div>

      {error && <div className="alert">{error}</div>}

      {!team && (
        <div className="team-join-grid">
          <div className="team-join-card">
            <h3>Создать команду</h3>
            <p className="mono" style={{ color: 'var(--text-dim)', fontSize: 12 }}>
              {comp?.min_team_size && comp?.max_team_size
                ? `размер: ${comp.min_team_size}–${comp.max_team_size}`
                : 'размер не ограничен'}
            </p>
            <div className="field">
              <label>Название</label>
              <input
                value={newTeamName}
                onChange={(e) => setNewTeamName(e.target.value)}
                placeholder="Red Team"
              />
            </div>
            <button
              className="btn btn-primary"
              disabled={busy || newTeamName.trim().length < 2}
              onClick={() => run(
                () => api.createTeam(slug, newTeamName.trim()),
                () => {
                  push({
                    type: 'team.created',
                    title: 'Команда создана',
                    message: newTeamName.trim(),
                    level: 'success',
                    link: `/competitions/${slug}/team`,
                  })
                  setNewTeamName('')
                },
              )}
            >
              Создать
            </button>
          </div>

          <div className="team-join-card">
            <h3>Присоединиться по коду</h3>
            <div className="field">
              <label>Invite-код</label>
              <input
                className="mono"
                value={joinCode}
                onChange={(e) => setJoinCode(e.target.value)}
                placeholder="abcd1234"
              />
            </div>
            <button
              className="btn"
              disabled={busy || !joinCode.trim()}
              onClick={() => run(
                () => api.joinByCode(slug, joinCode.trim()),
                () => {
                  push({
                    type: 'team.joined',
                    title: 'Вы присоединились к команде',
                    level: 'success',
                    link: `/competitions/${slug}/team`,
                  })
                  setJoinCode('')
                },
              )}
            >
              Присоединиться
            </button>
          </div>
        </div>
      )}

      {team && (
        <div className="team-panel">
          <div className="team-head">
            <h2>{team.name}</h2>
            <span className="mono badge">статус: {team.status}</span>
            <span className="mono badge">
              состав: {team.member_count}
              {team.max_team_size ? ` / ${team.max_team_size}` : ''}
            </span>
          </div>

          {team.invite_code && (
            <div className="team-invite-code mono">
              invite-код: <strong>{team.invite_code}</strong>
            </div>
          )}

          <h3>Состав</h3>
          <ul className="team-members">
            {team.members?.map((m) => (
              <li key={m.user_id} className={`team-member status-${m.status}`}>
                <span className="mono">{m.username}</span>
                <span className="role-tag">{m.role}</span>
                <span className="status-tag">{m.status}</span>
                {team.captain_id !== m.user_id && m.status === 'accepted' && (
                  <button
                    className="btn btn-danger"
                    disabled={busy}
                    onClick={() => run(
                      () => api.kickMember(slug, team.id, m.user_id),
                      () => push({
                        type: 'team.member.kicked',
                        title: 'Участник исключён',
                        message: m.username,
                        level: 'warning',
                      }),
                    )}
                  >
                    Кикнуть
                  </button>
                )}
              </li>
            ))}
          </ul>

          {team.members?.some((m) => m.user_id === team.captain_id && m.status === 'accepted') && (
            <div className="team-invite-block">
              <h3>Пригласить участника</h3>
              <div className="team-invite-row">
                <input
                  value={inviteUsername}
                  onChange={(e) => setInviteUsername(e.target.value)}
                  placeholder="username"
                />
                <button
                  className="btn"
                  disabled={busy || !inviteUsername.trim()}
                  onClick={() => run(
                    () => api.inviteToTeam(slug, team.id, inviteUsername.trim()),
                    () => {
                      push({
                        type: 'team.invite',
                        title: 'Приглашение отправлено',
                        message: inviteUsername.trim(),
                        level: 'info',
                      })
                      setInviteUsername('')
                    },
                  )}
                >
                  Пригласить
                </button>
              </div>
            </div>
          )}

          <div className="team-danger">
            <button
              className="btn btn-danger"
              disabled={busy}
              onClick={() => {
                if (confirm('Распустить команду?')) {
                  run(
                    () => api.disbandTeam(slug, team.id),
                    () => {
                      push({
                        type: 'team.disbanded',
                        title: 'Команда распущена',
                        message: team.name,
                        level: 'warning',
                      })
                      navigate(`/competitions/${slug}`)
                    },
                  )
                }
              }}
            >
              Распустить команду
            </button>
          </div>
        </div>
      )}

      {invitations.length > 0 && (
        <div className="team-panel" style={{ marginTop: 20 }}>
          <h3>Ваши приглашения</h3>
          <ul className="team-members">
            {invitations.map((t) => (
              <li key={t.id} className="team-member">
                <span>{t.name} (капитан: {t.captain_username})</span>
                <div style={{ display: 'flex', gap: 8 }}>
                  <button
                    className="btn btn-primary"
                    disabled={busy}
                    onClick={() => run(
                      () => api.acceptInvite(slug, t.id),
                      () => push({
                        type: 'team.invite.accepted',
                        title: 'Вы приняли приглашение',
                        message: t.name,
                        level: 'success',
                      }),
                    )}
                  >
                    Принять
                  </button>
                  <button
                    className="btn"
                    disabled={busy}
                    onClick={() => run(
                      () => api.declineInvite(slug, t.id),
                      () => push({
                        type: 'team.invite.declined',
                        title: 'Приглашение отклонено',
                        message: t.name,
                        level: 'info',
                      }),
                    )}
                  >
                    Отклонить
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}