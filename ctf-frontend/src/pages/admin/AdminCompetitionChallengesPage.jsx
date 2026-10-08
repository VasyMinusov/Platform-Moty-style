import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import './AdminCompetitions.css'

const BUILD_LABEL = {
  pending: 'ожидает',
  validating: 'валидация',
  building: 'сборка…',
  ready: 'готова',
  failed: 'ошибка',
  disabled: 'отключена',
}

export default function AdminCompetitionChallengesPage() {
  const { slug } = useParams()
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [openBuildLog, setOpenBuildLog] = useState(null)
  const [buildLog, setBuildLog] = useState('')
  const [drag, setDrag] = useState(false)
  const fileRef = useRef(null)
  const pollRef = useRef(null)

  useEffect(() => { load() }, [slug])
  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current) }, [])

  async function load() {
    setLoading(true); setError(null)
    try {
      setItems(await api.adminListChallenges(slug))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Ошибка')
    } finally { setLoading(false) }
  }

  async function upload(file) {
    if (!file) return
    setBusy(true); setError(null)
    try {
      await api.adminUploadChallenge(slug, file)
      await load()
      // Начинаем опрашивать статус сборки у всех не готовых заданий.
      startPolling()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Ошибка загрузки')
    } finally { setBusy(false) }
  }

  function startPolling() {
    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = setInterval(async () => {
      try {
        const data = await api.adminListChallenges(slug)
        setItems(data)
        const stillBuilding = data.some((c) =>
          c.kind === 'docker' && ['pending', 'building'].includes(c.build_status))
        if (!stillBuilding) {
          clearInterval(pollRef.current); pollRef.current = null
        }
      } catch { /* ignore */ }
    }, 2500)
  }

  async function rebuild(chSlug) {
    setBusy(true); setError(null)
    try {
      await api.adminRebuildChallenge(slug, chSlug)
      await load()
      startPolling()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Ошибка')
    } finally { setBusy(false) }
  }

  async function remove(chSlug) {
    if (!confirm(`Удалить задание "${chSlug}"?`)) return
    setBusy(true); setError(null)
    try {
      await api.adminDeleteChallenge(slug, chSlug)
      await load()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Ошибка')
    } finally { setBusy(false) }
  }

  async function showBuildLog(chSlug) {
    setOpenBuildLog(chSlug)
    setBuildLog('')
    try {
      const s = await api.adminBuildStatus(slug, chSlug)
      setBuildLog(s.build_log || '(пусто)')
    } catch (e) {
      setBuildLog(e instanceof ApiError ? e.message : 'Ошибка')
    }
  }

  async function promote(chSlug) {
    if (!confirm(`Промоутнуть "${chSlug}" в глобальные задания?`)) return
    setBusy(true); setError(null)
    try {
      const r = await api.adminPromoteChallenge(slug, chSlug, { enabled: true })
      alert(`Глобальное задание создано: ${r.slug} (#${r.global_challenge_id})`)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Ошибка промоушена')
    } finally { setBusy(false) }
  }

  return (
    <div>
      <div className="page-head">
        <div>
          <span className="eyebrow mono">{slug}</span>
          <h1>Задания</h1>
        </div>
        <Link to={`/admin/competitions`} className="btn">← К списку</Link>
      </div>

      {error && <div className="alert">{error}</div>}

      <div
        className={`zip-drop${drag ? ' drag' : ''}`}
        onDragOver={(e) => { e.preventDefault(); setDrag(true) }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault(); setDrag(false)
          const f = e.dataTransfer.files?.[0]
          if (f) upload(f)
        }}
        onClick={() => fileRef.current?.click()}
      >
        <p>
          <strong>Перетащите ZIP</strong> с заданием сюда или нажмите,
          чтобы выбрать файл. Один ZIP = один челлендж.
        </p>
        <input
          ref={fileRef}
          type="file"
          accept=".zip"
          style={{ display: 'none' }}
          onChange={(e) => {
            const f = e.target.files?.[0]
            e.target.value = ''
            if (f) upload(f)
          }}
        />
        {busy && <p className="mono" style={{ color: 'var(--accent)' }}>Загрузка…</p>}
      </div>

      {loading ? (
        <p className="mono" style={{ color: 'var(--text-dim)' }}>загрузка…</p>
      ) : items.length === 0 ? (
        <div className="empty-state"><p>Заданий нет.</p></div>
      ) : (
        <div className="adm-table-wrap" style={{ marginTop: 20 }}>
          <table className="adm-table">
            <thead>
              <tr>
                <th>#</th>
                <th>slug</th>
                <th>title</th>
                <th>kind</th>
                <th>type</th>
                <th>difficulty</th>
                <th>points</th>
                <th>build</th>
                <th>действия</th>
              </tr>
            </thead>
            <tbody>
              {items.map((c) => (
                <tr key={c.id}>
                  <td className="mono">#{c.id}</td>
                  <td className="mono">{c.slug}</td>
                  <td>{c.title}</td>
                  <td className="mono">{c.kind}</td>
                  <td className="mono">{c.type}</td>
                  <td className="mono">{c.difficulty}</td>
                  <td className="mono">{c.points}</td>
                  <td>
                    <span className={`adm-badge build-${c.build_status}`}>
                      {BUILD_LABEL[c.build_status] || c.build_status}
                    </span>
                  </td>
                  <td>
                    <div className="actions">
                      <button
                        className="adm-btn-mini"
                        onClick={() => showBuildLog(c.slug)}
                      >
                        Лог
                      </button>
                      {c.kind === 'docker' && (
                        <button
                          className="adm-btn-mini"
                          disabled={busy}
                          onClick={() => rebuild(c.slug)}
                        >
                          Пересобрать
                        </button>
                      )}
                      {c.kind === 'docker' && c.build_status === 'ready' && (
                        <button
                          className="adm-btn-mini"
                          disabled={busy}
                          onClick={() => promote(c.slug)}
                        >
                          В глобальные
                        </button>
                      )}
                      <button
                        className="adm-btn-mini danger"
                        disabled={busy}
                        onClick={() => remove(c.slug)}
                      >
                        Удалить
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {openBuildLog && (
        <div className="adm-card" style={{ marginTop: 20 }}>
          <h3>Лог сборки: {openBuildLog}</h3>
          <div className="build-log">{buildLog}</div>
          <button className="btn" onClick={() => setOpenBuildLog(null)}>Закрыть</button>
        </div>
      )}
    </div>
  )
}