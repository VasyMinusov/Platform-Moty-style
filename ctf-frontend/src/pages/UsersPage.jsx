import { useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import { useAuth } from '../context/AuthContext'
import './UsersPage.css'

const ROLE_LABELS = {
  student: 'студент',
  moderator: 'модератор',
  admin: 'админ',
}

function StatusBadge({ status }) {
  if (!status) return null
  return <span className="user-status-badge mono">#{status}</span>
}

function UserRow({ user, isAdmin, currentUserId, onChanged, onError }) {
  const [statusDraft, setStatusDraft] = useState(user.status || '')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    setStatusDraft(user.status || '')
  }, [user.status])

  async function run(fn) {
    setBusy(true)
    try {
      await fn()
      await onChanged()
    } catch (err) {
      onError(err instanceof ApiError ? err.message : 'Операция не выполнена')
    } finally {
      setBusy(false)
    }
  }

  const statusDirty = (statusDraft.trim() || '') !== (user.status || '')

  return (
    <tr className={user.is_blocked ? 'user-row blocked' : 'user-row'}>
      <td className="mono dim">#{user.id}</td>
      <td>
        <div className="user-name-cell">
          <strong>{user.username}</strong>
          <StatusBadge status={user.status} />
          {user.is_blocked && <span className="user-blocked-tag mono">blocked</span>}
        </div>
      </td>
      <td className="dim">{user.email}</td>
      <td>
        {isAdmin && user.id !== currentUserId ? (
          <select
            className="role-select"
            value={user.role}
            disabled={busy}
            onChange={(e) => run(() => api.setUserRole(user.id, e.target.value))}
          >
            {Object.entries(ROLE_LABELS).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        ) : (
          <span className={`role-tag mono role-${user.role}`}>{ROLE_LABELS[user.role] || user.role}</span>
        )}
      </td>
      <td className="mono">{user.points}</td>
      <td>
        {isAdmin ? (
          <div className="user-actions">
            <div className="status-editor">
              <input
                value={statusDraft}
                onChange={(e) => setStatusDraft(e.target.value)}
                placeholder="статус…"
                maxLength={64}
                disabled={busy}
              />
              {statusDirty && (
                <button
                  className="btn"
                  disabled={busy}
                  onClick={() => run(() => api.updateUser(user.id, { status: statusDraft.trim() }))}
                >
                  Сохранить
                </button>
              )}
            </div>
            {user.role !== 'admin' && user.id !== currentUserId && (
              <button
                className={user.is_blocked ? 'btn' : 'btn btn-danger'}
                disabled={busy}
                onClick={() => run(() => api.updateUser(user.id, { is_blocked: !user.is_blocked }))}
              >
                {user.is_blocked ? 'Разблокировать' : 'Заблокировать'}
              </button>
            )}
          </div>
        ) : (
          <span className="dim" style={{ fontSize: 12 }}>только просмотр</span>
        )}
      </td>
    </tr>
  )
}

export default function UsersPage() {
  const { role, username } = useAuth()
  const isAdmin = role === 'admin'
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [filter, setFilter] = useState('')

  useEffect(() => {
    load()
  }, [])

  async function load() {
    setError(null)
    try {
      const data = await api.listUsers()
      setUsers(data)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось загрузить пользователей')
    } finally {
      setLoading(false)
    }
  }

  const me = users.find((u) => u.username === username)
  const q = filter.trim().toLowerCase()
  const visible = q
    ? users.filter((u) =>
        u.username.toLowerCase().includes(q) ||
        u.email.toLowerCase().includes(q) ||
        (u.status || '').toLowerCase().includes(q))
    : users

  return (
    <div>
      <div className="page-head">
        <div>
          <span className="eyebrow">персонал платформы</span>
          <h1>Пользователи</h1>
        </div>
        <input
          className="users-filter"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="поиск по имени, почте, статусу…"
        />
      </div>

      {!isAdmin && (
        <p className="admin-note">
          Вы вошли как <code className="mono">moderator</code> — список доступен только для просмотра.
        </p>
      )}

      {error && <div className="alert">{error}</div>}

      {loading ? (
        <p className="mono" style={{ color: 'var(--text-dim)' }}>загрузка…</p>
      ) : (
        <div className="users-table-wrap">
          <table className="users-table">
            <thead>
              <tr>
                <th>id</th>
                <th>пользователь</th>
                <th>почта</th>
                <th>роль</th>
                <th>очки</th>
                <th>{isAdmin ? 'действия' : ''}</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((u) => (
                <UserRow
                  key={u.id}
                  user={u}
                  isAdmin={isAdmin}
                  currentUserId={me?.id}
                  onChanged={load}
                  onError={setError}
                />
              ))}
              {visible.length === 0 && (
                <tr>
                  <td colSpan={6} className="dim" style={{ textAlign: 'center', padding: 24 }}>
                    Никого не найдено
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
