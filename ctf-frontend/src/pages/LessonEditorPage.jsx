import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import { MarkdownView } from '../components/MarkdownView'
import './Lessons.css'

const CYRILLIC = {
  а: 'a', б: 'b', в: 'v', г: 'g', д: 'd', е: 'e', ё: 'e', ж: 'zh', з: 'z',
  и: 'i', й: 'y', к: 'k', л: 'l', м: 'm', н: 'n', о: 'o', п: 'p', р: 'r',
  с: 's', т: 't', у: 'u', ф: 'f', х: 'h', ц: 'c', ч: 'ch', ш: 'sh', щ: 'sch',
  ъ: '', ы: 'y', ь: '', э: 'e', ю: 'yu', я: 'ya',
}

function slugify(text) {
  return text
    .toLowerCase()
    .split('')
    .map((ch) => CYRILLIC[ch] ?? ch)
    .join('')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 64)
}

const DRAFT_TEMPLATE = `# Название занятия

## Цели

Опишите, чему научится студент.

## Теория

Основной материал занятия. Поддерживается **Markdown**:

- списки
- \`код\`
- [ссылки](https://example.com)

\`\`\`bash
# блоки кода
curl http://target/
\`\`\`

## Практика

Задание для самостоятельного выполнения.
`

export default function LessonEditorPage() {
  const { slug } = useParams() // undefined на /lessons/new
  const isNew = !slug
  const navigate = useNavigate()

  const [form, setForm] = useState({ title: '', slug: '', summary: '', content_md: '' })
  const [slugTouched, setSlugTouched] = useState(false)
  const [showPreview, setShowPreview] = useState(true)
  const [loading, setLoading] = useState(!isNew)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (isNew) {
      setForm((f) => ({ ...f, content_md: DRAFT_TEMPLATE }))
      return
    }
    api.getLesson(slug)
      .then((l) => setForm({ title: l.title, slug: l.slug, summary: l.summary, content_md: l.content_md }))
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Занятие не найдено'))
      .finally(() => setLoading(false))
  }, [slug, isNew])

  function updateTitle(value) {
    setForm((f) => ({
      ...f,
      title: value,
      slug: isNew && !slugTouched ? slugify(value) : f.slug,
    }))
  }

  async function handleSave() {
    setSaving(true)
    setError(null)
    try {
      if (!form.title.trim()) throw new ApiError('Укажите название занятия', 0, null)
      if (!form.slug.trim()) throw new ApiError('Укажите slug занятия', 0, null)

      const payload = {
        title: form.title.trim(),
        slug: form.slug.trim(),
        summary: form.summary.trim(),
        content_md: form.content_md,
      }
      const saved = isNew
        ? await api.createLesson(payload)
        : await api.updateLesson(slug, payload)
      navigate(`/lessons/${saved.slug}`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Ошибка сохранения')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return <p className="mono" style={{ color: 'var(--text-dim)' }}>загрузка…</p>
  }

  return (
    <div>
      <div className="page-head">
        <div>
          <span className="eyebrow">редактор занятия</span>
          <h1>{isNew ? 'Новое занятие' : `Правка: ${form.title || slug}`}</h1>
        </div>
        <label className="preview-toggle mono">
          <input
            type="checkbox"
            checked={showPreview}
            onChange={(e) => setShowPreview(e.target.checked)}
          />
          превью
        </label>
      </div>

      {error && <div className="alert">{error}</div>}

      <div className="lesson-editor">
        <div className="lesson-editor-meta">
          <div className="field">
            <label>Название</label>
            <input
              value={form.title}
              onChange={(e) => updateTitle(e.target.value)}
              placeholder="Например: Введение в SQL-инъекции"
            />
          </div>
          <div className="field">
            <label>Slug (адрес страницы)</label>
            <input
              className="mono"
              value={form.slug}
              onChange={(e) => {
                setSlugTouched(true)
                setForm({ ...form, slug: e.target.value })
              }}
              placeholder="vvedenie-v-sql-injections"
            />
          </div>
          <div className="field">
            <label>Краткое описание</label>
            <input
              value={form.summary}
              onChange={(e) => setForm({ ...form, summary: e.target.value })}
              placeholder="Одно предложение о том, что внутри занятия"
              maxLength={500}
            />
          </div>
        </div>

        <div className={showPreview ? 'lesson-editor-panes' : 'lesson-editor-panes single'}>
          <div className="field">
            <label>Текст (Markdown)</label>
            <textarea
              value={form.content_md}
              onChange={(e) => setForm({ ...form, content_md: e.target.value })}
              spellCheck={false}
            />
          </div>
          {showPreview && (
            <div className="field">
              <label>Предпросмотр</label>
              <MarkdownView source={form.content_md} className="lesson-preview" />
            </div>
          )}
        </div>

        <div style={{ display: 'flex', gap: 10, marginTop: 8 }}>
          <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
            {saving ? 'Сохранение…' : isNew ? 'Создать занятие' : 'Сохранить'}
          </button>
          <button className="btn" onClick={() => navigate(-1)} disabled={saving}>
            Отмена
          </button>
        </div>
      </div>
    </div>
  )
}
