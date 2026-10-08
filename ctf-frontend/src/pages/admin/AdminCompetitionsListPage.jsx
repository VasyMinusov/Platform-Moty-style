import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import './AdminCompetitions.css'

const STATUS_LABEL = {
  draft: 'черновик',
  announced: 'анонс',
  registration_open: 'регистрация',
  registration_closed: 'регистрация закрыта',
  running: 'идёт',
  paused: 'пауза',
  finished: 'завершено',
  cancelled: 'отменено',
}

const NEXT_ACTIONS = {
  draft: [['publish', 'Опубликовать']],
  announced: [['open-registration', 'Открыть регистрацию']],
  registration_open: [['close-registration', 'Закрыть регистрацию']],
  registration_closed: [['start', 'Запустить']],
  running: [['pause', 'Пауза'], ['finish', 'Завершить']],
  paused: [['resume', 'Продолжить'], ['finish', 'Завершить']],
  finished: [],
  cancelled: [],
}

export default function AdminCompetitionsListPage() {
  const navigate = useNavigate()
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [filter, setFilter] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => { load() }, [])

  async function load() {
    setLoading(true); setError(null)
    try {
      setItems(await api.adminListCompetitions())
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Ошибка загрузки')
    } finally { setLoading(false) }
  }

  async function runAction(slug, action) {
    setBusy(true); setError(null)
    const fn = {
      'publish': api.adminPublishCompetition,
      'open-registration': api.adminOpenRegistration,
      'close-registration': api.adminCloseRegistration,
      'start': api.adminStartCompetition,
      'pause': api.adminPauseCompetition,
      'resume': api.adminResumeCompetition,
      'finish': api.adminFinishCompetition,
      'cancel': api.adminCancelCompetition,
    }[action]
    try {
      if (action === 'finish' && !confirm('Завершить соревнование? Все инстансы будут остановлены.')) return
      if (action === 'cancel' && !confirm('Отменить соревнование?')) return
      await fn(slug)
      await load()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Ошибка')
    } finally { setBusy(false) }
  }

  async function remove(slug) {
    if (!confirm(`Удалить соревнование "${slug}"?`)) return
    setBusy(true); setError(null)
    try {
      await api.adminDeleteCompetition(slug)
      await load()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Ошибка')
    } finally { setBusy(false) }
  }

  const q = filter.trim().toLowerCase()
  const visible = q
    ? items.filter((c) =>
        c.slug.toLowerCase().includes(q) ||
        c.title.toLowerCase().includes(q) ||
        c.status.toLowerCase().includes(q))
    : items

  return (
    <div>
      <div className="page-head">
        <div>
          <span className="eyebrow">администрирование</span>
          <h1>Соревнования</h1>
        </div>
        <button className="btn btn-primary" onClick={() => navigate('/admin/competitions/new')}>
          + Создать соревнование
        </button>
      </div>

      <div className="adm-toolbar">
        <input
          type="search"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="поиск по slug, названию, статусу…"
        />
        <button className="btn" onClick={load} disabled={loading}>Обновить</button>
      </div>

      {error && <div className="alert">{error}</div>}

      {loading ? (
        <p className="mono" style={{ color: 'var(--text-dim)' }}>загрузка…</p>
      ) : visible.length === 0 ? (
        <div className="empty-state"><p>Соревнований нет.</p></div>
      ) : (
        <div className="adm-table-wrap">
          <table className="adm-table">
            <thead>
              <tr>
                <th>slug</th>
                <th>название</th>
                <th>режим</th>
                <th>статус</th>
                <th>старт</th>
                <th>финиш</th>
                <th>действия</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((c) => (
                <tr key={c.id}>
                  <td className="mono">{c.slug}</td>
                  <td>
                    <Link to={`/competitions/${c.slug}`}>{c.title}</Link>
                  </td>
                  <td className="mono">{c.mode}</td>
                  <td>
                    <span className={`adm-badge status-${c.status}`}>
                      {STATUS_LABEL[c.status] || c.status}
                    </span>
                  </td>
                  <td className="mono" style={{ fontSize: 11 }}>
                    {c.starts_at ? new Date(c.starts_at).toLocaleString('ru-RU') : '—'}
                  </td>
                  <td className="mono" style={{ fontSize: 11 }}>
                    {c.ends_at ? new Date(c.ends_at).toLocaleString('ru-RU') : '—'}
                  </td>
                  <td>
                    <div className="actions">
                      <button
                        className="adm-btn-mini"
                        onClick={() => navigate(`/admin/competitions/${c.slug}/edit`)}
                      >
                        Изменить
                      </button>
                      <button
                        className="adm-btn-mini"
                        onClick={() => navigate(`/admin/competitions/${c.slug}/applications`)}
                      >
                        Заявки
                      </button>
                      <button
                        className="adm-btn-mini"
                        onClick={() => navigate(`/admin/competitions/${c.slug}/challenges`)}
                      >
                        Задания
                      </button>
                      <button
                        className="adm-btn-mini"
                        onClick={() => navigate(`/admin/competitions/${c.slug}/teams`)}
                      >
                        Команды
                      </button>
                      <button
                        className="adm-btn-mini"
                        onClick={() => navigate(`/admin/competitions/${c.slug}/dashboard`)}
                      >
                        Дашборд
                      </button>
                      <button
                        className="adm-btn-mini"
                        onClick={() => navigate(`/admin/competitions/${c.slug}/appeals`)}
                      >
                        Апелляции
                      </button>
                      {(NEXT_ACTIONS[c.status] || []).map(([action, label]) => (
                        <button
                          key={action}
                          className="adm-btn-mini"
                          disabled={busy}
                          onClick={() => runAction(c.slug, action)}
                        >
                          {label}
                        </button>
                      ))}
                      {['draft', 'announced', 'cancelled'].includes(c.status) && (
                        <button
                          className="adm-btn-mini danger"
                          disabled={busy}
                          onClick={() => remove(c.slug)}
                        >
                          Удалить
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}