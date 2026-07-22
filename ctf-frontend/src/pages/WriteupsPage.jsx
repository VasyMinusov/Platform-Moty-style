import { useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import './WriteupsPage.css'

const EMPTY_WRITEUP = {
  challenge_slug: '',
  title: '',
  content_json: JSON.stringify({
    description: 'Описание уязвимости и цели задания',
    steps: [
      {
        step: 1,
        title: 'Разведка',
        detail: 'Опишите, что нужно заметить в приложении',
        command: 'curl http://target/',
        screenshot: ''
      },
      {
        step: 2,
        title: 'Эксплуатация',
        detail: 'Опишите шаги эксплуатации',
        command: '',
        screenshot: ''
      }
    ],
    flag: 'flag{...}'
  }, null, 2)
}

export default function WriteupsPage() {
  const [writeups, setWriteups] = useState([])
  const [challenges, setChallenges] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [editing, setEditing] = useState(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    load()
  }, [])

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const [wData, cData] = await Promise.all([
        api.listWriteups(),
        api.listChallenges()
      ])
      setWriteups(wData)
      setChallenges(cData)
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setError('Доступ только для администраторов.')
      } else {
        setError(err instanceof ApiError ? err.message : 'Ошибка загрузки')
      }
    } finally {
      setLoading(false)
    }
  }

  function startNew() {
    setEditing({ ...EMPTY_WRITEUP })
  }

  function startEdit(w) {
    setEditing({
      challenge_slug: w.challenge_slug,
      title: w.title,
      content_json: typeof w.content_json === 'string'
        ? w.content_json
        : JSON.stringify(w.content_json, null, 2)
    })
  }

  async function handleSave() {
    setSaving(true)
    setError(null)
    try {
      JSON.parse(editing.content_json)

      const existing = writeups.find(w => w.challenge_slug === editing.challenge_slug)
      if (existing) {
        await api.updateWriteup(editing.challenge_slug, {
          title: editing.title,
          content_json: editing.content_json
        })
      } else {
        await api.createWriteup({
          challenge_slug: editing.challenge_slug,
          title: editing.title,
          content_json: editing.content_json
        })
      }
      setEditing(null)
      await load()
    } catch (err) {
      if (err instanceof SyntaxError) {
        setError('Невалидный JSON в поле содержимого: ' + err.message)
      } else {
        setError(err instanceof ApiError ? err.message : 'Ошибка сохранения')
      }
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete(slug) {
    if (!confirm(`Удалить write-up для «${slug}»?`)) return
    try {
      await api.deleteWriteup(slug)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Ошибка удаления')
    }
  }

  const availableSlugs = challenges
    .filter(c => !writeups.some(w => w.challenge_slug === c.slug))
    .map(c => c.slug)

  if (loading) {
    return <p className="mono" style={{ color: 'var(--text-dim)' }}>загрузка…</p>
  }

  if (editing) {
    const isExisting = writeups.some(w => w.challenge_slug === editing.challenge_slug)
    return (
      <div>
        <div className="page-head">
          <div>
            <span className="eyebrow">редактор</span>
            <h1>{isExisting ? 'Редактировать' : 'Новый'} write-up</h1>
          </div>
        </div>

        {error && <div className="alert">{error}</div>}

        <div className="writeup-editor">
          <div className="field">
            <label>Задание</label>
            {isExisting ? (
              <input value={editing.challenge_slug} disabled />
            ) : (
              <select
                value={editing.challenge_slug}
                onChange={(e) => setEditing({ ...editing, challenge_slug: e.target.value })}
              >
                <option value="">— выберите задание —</option>
                {availableSlugs.map(s => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            )}
          </div>

          <div className="field">
            <label>Название решения</label>
            <input
              value={editing.title}
              onChange={(e) => setEditing({ ...editing, title: e.target.value })}
              placeholder="Например: SQL Injection — пошаговое решение"
            />
          </div>

          <div className="field">
            <label>Содержимое (JSON)</label>
            <textarea
              value={editing.content_json}
              onChange={(e) => setEditing({ ...editing, content_json: e.target.value })}
              spellCheck={false}
            />
            <div className="json-hint">
              {`{
  "description": "...",
  "steps": [
    { "step": 1, "title": "...", "detail": "...", "command": "...", "screenshot": "" }
  ],
  "flag": "flag{...}"
}`}
            </div>
          </div>

          <div style={{ display: 'flex', gap: 10, marginTop: 8 }}>
            <button className="btn btn-primary" onClick={handleSave} disabled={saving || !editing.challenge_slug}>
              {saving ? 'Сохранение…' : 'Сохранить'}
            </button>
            <button className="btn" onClick={() => setEditing(null)} disabled={saving}>
              Отмена
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div>
      <div className="page-head">
        <div>
          <span className="eyebrow">база знаний</span>
          <h1>Write-ups</h1>
        </div>
        <button className="btn btn-primary" onClick={startNew}>
          + Добавить write-up
        </button>
      </div>

      {error && <div className="alert">{error}</div>}

      {writeups.length === 0 ? (
        <div className="writeups-empty">
          <p>Нет сохранённых write-ups.</p>
          <button className="btn btn-primary" onClick={startNew}>
            Создать первое решение
          </button>
        </div>
      ) : (
        <div className="admin-grid">
          {writeups.map((w) => (
            <div key={w.challenge_slug} className="writeup-card">
              <span className="eyebrow mono">{w.challenge_slug}</span>
              <h3>{w.title}</h3>
              <span className="meta">
                обновлено: {new Date(w.updated_at).toLocaleString('ru-RU')}
              </span>
              <div className="actions">
                <button className="btn" onClick={() => startEdit(w)}>Редактировать</button>
                <button className="btn btn-danger" onClick={() => handleDelete(w.challenge_slug)}>
                  Удалить
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

