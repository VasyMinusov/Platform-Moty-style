import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import { useAuth } from '../../context/AuthContext'
import './AdminCompetitions.css'

const STEPS = [
  ['basic', 'Основное'],
  ['mode', 'Режим и команды'],
  ['schedule', 'Расписание'],
  ['visibility', 'Видимость'],
  ['scoring', 'Очки'],
  ['infra', 'Инфраструктура'],
  ['moderators', 'Модераторы'],
  ['publish', 'Публикация'],
]

const DEFAULT_SCORING = {
  mode: 'fixed',
  default_points: 100,
  per_challenge_override: {},
  dynamic_decay: {
    decay_type: 'step',
    decay_step: 5,
    decay_interval: 5,
    min_points: 50,
    max_points: 1000,
    compute_at: 'on_solve',
  },
  placement: {
    places: [
      { place: 1, points: 1500 },
      { place: 2, points: 1000 },
    ],
    default_points: 100,
    apply_at: 'finish',
  },
  hint_penalty: { apply: true },
  bonuses: [],
  team_scoring: 'team_only',
}

const DEFAULT_NETWORK = { isolated: true, allow_internet: false, extra_hosts: [] }

const EMPTY = {
  slug: '',
  title: '',
  summary: '',
  description_md: '',
  rules_md: '',
  visibility: 'hidden',
  mode: 'individual',
  registration_opens_at: '',
  registration_closes_at: '',
  starts_at: '',
  ends_at: '',
  allow_late_application: false,
  allow_late_withdraw: false,
  max_participants: '',
  max_teams: '',
  min_team_size: '',
  max_team_size: '',
  public_team_roster: false,
  leaderboard_visibility: 'participants',
  tie_breaker: 'last_solve_time',
  scoring_config: DEFAULT_SCORING,
  network_config: DEFAULT_NETWORK,
  instance_ttl_seconds: 3600,
  max_instances_per_user: '',
  max_instances_per_team: '',
  max_instances_per_competition: '',
}

function toIsoOrNull(value) {
  if (!value) return null
  return new Date(value).toISOString()
}

function fromIso(value) {
  if (!value) return ''
  const d = new Date(value)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(
    d.getHours(),
  )}:${pad(d.getMinutes())}`
}

function numOrNull(v) {
  if (v === '' || v === null || v === undefined) return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

export default function AdminCompetitionEditorPage() {
  const { slug } = useParams()
  const isNew = !slug
  const navigate = useNavigate()
  const { role } = useAuth()
  const isAdmin = role === 'admin'

  const [step, setStep] = useState('basic')
  const [form, setForm] = useState(EMPTY)
  const [loading, setLoading] = useState(!isNew)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [moderators, setModerators] = useState([])
  const [modUserId, setModUserId] = useState('')
  const [modRole, setModRole] = useState('helper')

  useEffect(() => {
    if (isNew) return
    api
      .adminGetCompetition(slug)
      .then((c) => {
        setForm({
          ...EMPTY,
          ...c,
          registration_opens_at: fromIso(c.registration_opens_at),
          registration_closes_at: fromIso(c.registration_closes_at),
          starts_at: fromIso(c.starts_at),
          ends_at: fromIso(c.ends_at),
          scoring_config: { ...DEFAULT_SCORING, ...(c.scoring_config || {}) },
          network_config: { ...DEFAULT_NETWORK, ...(c.network_config || {}) },
          max_participants: c.max_participants ?? '',
          max_teams: c.max_teams ?? '',
          min_team_size: c.min_team_size ?? '',
          max_team_size: c.max_team_size ?? '',
          max_instances_per_user: c.max_instances_per_user ?? '',
          max_instances_per_team: c.max_instances_per_team ?? '',
          max_instances_per_competition: c.max_instances_per_competition ?? '',
        })
        return api.adminListModerators(slug)
      })
      .then((m) => setModerators(m || []))
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Ошибка'))
      .finally(() => setLoading(false))
  }, [slug, isNew])

  function setField(key, value) {
    setForm((f) => ({ ...f, [key]: value }))
  }

  function buildPayload() {
    const p = {
      title: form.title.trim(),
      summary: form.summary.trim(),
      description_md: form.description_md,
      rules_md: form.rules_md,
      visibility: form.visibility,
      mode: form.mode,
      registration_opens_at: toIsoOrNull(form.registration_opens_at),
      registration_closes_at: toIsoOrNull(form.registration_closes_at),
      starts_at: toIsoOrNull(form.starts_at),
      ends_at: toIsoOrNull(form.ends_at),
      allow_late_application: !!form.allow_late_application,
      allow_late_withdraw: !!form.allow_late_withdraw,
      max_participants: numOrNull(form.max_participants),
      max_teams: numOrNull(form.max_teams),
      min_team_size: numOrNull(form.min_team_size),
      max_team_size: numOrNull(form.max_team_size),
      public_team_roster: !!form.public_team_roster,
      leaderboard_visibility: form.leaderboard_visibility,
      tie_breaker: form.tie_breaker,
      scoring_config: form.scoring_config,
      network_config: form.network_config,
      instance_ttl_seconds: Number(form.instance_ttl_seconds) || 3600,
      max_instances_per_user: numOrNull(form.max_instances_per_user),
      max_instances_per_team: numOrNull(form.max_instances_per_team),
      max_instances_per_competition: numOrNull(form.max_instances_per_competition),
    }
    if (isNew) p.slug = form.slug.trim()
    return p
  }

  async function save() {
    setSaving(true)
    setError(null)
    try {
      if (!form.title.trim()) throw new ApiError('Укажите название', 0, null)
      if (isNew && !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(form.slug)) {
        throw new ApiError(
          'Slug должен быть kebab-case: латиница, цифры, дефисы',
          0,
          null,
        )
      }
      const payload = buildPayload()
      const saved = isNew
        ? await api.adminCreateCompetition(payload)
        : await api.adminUpdateCompetition(slug, payload)
      navigate(`/admin/competitions/${saved.slug}/edit`)
      if (isNew) setStep('moderators')
      else
        setForm((f) => ({
          ...f,
          ...saved,
          registration_opens_at: fromIso(saved.registration_opens_at),
          registration_closes_at: fromIso(saved.registration_closes_at),
          starts_at: fromIso(saved.starts_at),
          ends_at: fromIso(saved.ends_at),
        }))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Ошибка сохранения')
    } finally {
      setSaving(false)
    }
  }

  async function addModerator() {
    const uid = numOrNull(modUserId)
    if (uid === null) return
    setSaving(true)
    setError(null)
    try {
      await api.adminAddModerator(slug, { user_id: uid, role: modRole })
      setModUserId('')
      setModerators(await api.adminListModerators(slug))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Ошибка')
    } finally {
      setSaving(false)
    }
  }

  async function removeModerator(uid) {
    if (!confirm(`Снять модератора #${uid}?`)) return
    setSaving(true)
    setError(null)
    try {
      await api.adminRemoveModerator(slug, uid)
      setModerators(await api.adminListModerators(slug))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Ошибка')
    } finally {
      setSaving(false)
    }
  }

  async function publish() {
    setSaving(true)
    setError(null)
    try {
      await api.adminPublishCompetition(slug)
      const c = await api.adminGetCompetition(slug)
      setForm((f) => ({
        ...f,
        ...c,
        registration_opens_at: fromIso(c.registration_opens_at),
        registration_closes_at: fromIso(c.registration_closes_at),
        starts_at: fromIso(c.starts_at),
        ends_at: fromIso(c.ends_at),
      }))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Ошибка')
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
          <span className="eyebrow">
            {isNew ? 'новое соревнование' : `#${slug}`}
          </span>
          <h1>{isNew ? 'Создание соревнования' : form.title}</h1>
        </div>
        <button className="btn" onClick={() => navigate('/admin/competitions')}>
          ← К списку
        </button>
      </div>

      {error && <div className="alert">{error}</div>}

      <div className="wiz">
        <nav className="wiz-steps">
          {STEPS.map(([key, label]) => (
            <button
              key={key}
              className={`wiz-step-btn${step === key ? ' active' : ''}`}
              onClick={() => setStep(key)}
            >
              {label}
            </button>
          ))}
        </nav>

        <div className="wiz-body">
          {step === 'basic' && (
            <BasicStep form={form} setField={setField} isNew={isNew} />
          )}
          {step === 'mode' && <ModeStep form={form} setField={setField} />}
          {step === 'schedule' && (
            <ScheduleStep form={form} setField={setField} />
          )}
          {step === 'visibility' && (
            <VisibilityStep form={form} setField={setField} />
          )}
          {step === 'scoring' && (
            <ScoringStep form={form} setField={setField} />
          )}
          {step === 'infra' && <InfraStep form={form} setField={setField} />}
          {step === 'moderators' && (
            <ModeratorsStep
              isNew={isNew}
              isAdmin={isAdmin}
              moderators={moderators}
              modUserId={modUserId}
              setModUserId={setModUserId}
              modRole={modRole}
              setModRole={setModRole}
              onAdd={addModerator}
              onRemove={removeModerator}
              busy={saving}
            />
          )}
          {step === 'publish' && (
            <PublishStep
              isNew={isNew}
              form={form}
              isAdmin={isAdmin}
              onPublish={publish}
              busy={saving}
            />
          )}

          <div className="wiz-foot">
            <button
              className="btn"
              onClick={() => navigate('/admin/competitions')}
              disabled={saving}
            >
              Отмена
            </button>
            {step !== 'publish' && (
              <button
                className="btn btn-primary"
                onClick={save}
                disabled={saving}
              >
                {saving ? 'Сохранение…' : isNew ? 'Создать' : 'Сохранить'}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Шаги ────────────────────────────────────────────────────────────

function BasicStep({ form, setField, isNew }) {
  return (
    <>
      <h2>Основное</h2>
      <div className="wiz-row">
        <div className="wiz-field">
          <label>Slug</label>
          <input
            className="mono"
            value={form.slug}
            disabled={!isNew}
            onChange={(e) => setField('slug', e.target.value)}
            placeholder="ctf-2026-spring"
          />
        </div>
        <div className="wiz-field">
          <label>Название</label>
          <input
            value={form.title}
            onChange={(e) => setField('title', e.target.value)}
            placeholder="Spring CTF 2026"
          />
        </div>
      </div>
      <div className="wiz-field">
        <label>Краткое описание</label>
        <input
          value={form.summary}
          maxLength={500}
          onChange={(e) => setField('summary', e.target.value)}
          placeholder="Одно предложение для карточки анонса"
        />
      </div>
      <div className="wiz-field">
        <label>Описание (Markdown)</label>
        <textarea
          value={form.description_md}
          onChange={(e) => setField('description_md', e.target.value)}
        />
      </div>
      <div className="wiz-field">
        <label>Правила (Markdown)</label>
        <textarea
          value={form.rules_md}
          onChange={(e) => setField('rules_md', e.target.value)}
        />
      </div>
    </>
  )
}

function ModeStep({ form, setField }) {
  const teamMode = form.mode !== 'individual'
  return (
    <>
      <h2>Режим и команды</h2>
      <div className="wiz-field">
        <label>Режим</label>
        <select value={form.mode} onChange={(e) => setField('mode', e.target.value)}>
          <option value="individual">Индивидуальный</option>
          <option value="team">Командный</option>
          <option value="both">Индивидуальный и командный</option>
        </select>
      </div>
      {teamMode && (
        <>
          <div className="wiz-row-3">
            <div className="wiz-field">
              <label>Мин. состав</label>
              <input
                type="number"
                min="1"
                value={form.min_team_size}
                onChange={(e) => setField('min_team_size', e.target.value)}
              />
            </div>
            <div className="wiz-field">
              <label>Макс. состав</label>
              <input
                type="number"
                min="1"
                value={form.max_team_size}
                onChange={(e) => setField('max_team_size', e.target.value)}
              />
            </div>
            <div className="wiz-field">
              <label>Макс. команд</label>
              <input
                type="number"
                min="1"
                value={form.max_teams}
                onChange={(e) => setField('max_teams', e.target.value)}
              />
            </div>
          </div>
          <div className="wiz-field">
            <label>
              <input
                type="checkbox"
                checked={form.public_team_roster}
                onChange={(e) => setField('public_team_roster', e.target.checked)}
              />{' '}
              Показывать состав команд другим участникам
            </label>
          </div>
        </>
      )}
      <div className="wiz-field">
        <label>Макс. участников (0 = без ограничения)</label>
        <input
          type="number"
          min="0"
          value={form.max_participants}
          onChange={(e) => setField('max_participants', e.target.value)}
        />
      </div>
    </>
  )
}

function ScheduleStep({ form, setField }) {
  return (
    <>
      <h2>Расписание</h2>
      <div className="wiz-row">
        <div className="wiz-field">
          <label>Регистрация открыта</label>
          <input
            type="datetime-local"
            value={form.registration_opens_at}
            onChange={(e) => setField('registration_opens_at', e.target.value)}
          />
        </div>
        <div className="wiz-field">
          <label>Регистрация закрыта</label>
          <input
            type="datetime-local"
            value={form.registration_closes_at}
            onChange={(e) => setField('registration_closes_at', e.target.value)}
          />
        </div>
      </div>
      <div className="wiz-row">
        <div className="wiz-field">
          <label>Старт</label>
          <input
            type="datetime-local"
            value={form.starts_at}
            onChange={(e) => setField('starts_at', e.target.value)}
          />
        </div>
        <div className="wiz-field">
          <label>Финиш</label>
          <input
            type="datetime-local"
            value={form.ends_at}
            onChange={(e) => setField('ends_at', e.target.value)}
          />
        </div>
      </div>
      <div className="wiz-row">
        <div className="wiz-field">
          <label>
            <input
              type="checkbox"
              checked={form.allow_late_application}
              onChange={(e) => setField('allow_late_application', e.target.checked)}
            />{' '}
            Разрешить поздние заявки
          </label>
        </div>
        <div className="wiz-field">
          <label>
            <input
              type="checkbox"
              checked={form.allow_late_withdraw}
              onChange={(e) => setField('allow_late_withdraw', e.target.checked)}
            />{' '}
            Разрешить поздний отзыв заявок
          </label>
        </div>
      </div>
    </>
  )
}

function VisibilityStep({ form, setField }) {
  return (
    <>
      <h2>Видимость</h2>
      <div className="wiz-row">
        <div className="wiz-field">
          <label>Видимость соревнования</label>
          <select
            value={form.visibility}
            onChange={(e) => setField('visibility', e.target.value)}
          >
            <option value="public">Публичное</option>
            <option value="private">Приватное</option>
            <option value="hidden">Скрытое</option>
          </select>
        </div>
        <div className="wiz-field">
          <label>Видимость лидерборда</label>
          <select
            value={form.leaderboard_visibility}
            onChange={(e) => setField('leaderboard_visibility', e.target.value)}
          >
            <option value="public">Публичный</option>
            <option value="participants">Только участникам</option>
            <option value="hidden">Скрытый</option>
          </select>
        </div>
      </div>
      <div className="wiz-field">
        <label>Tie-breaker</label>
        <select
          value={form.tie_breaker}
          onChange={(e) => setField('tie_breaker', e.target.value)}
        >
          <option value="last_solve_time">По времени последнего решения</option>
          <option value="first_solve_time">По времени первого решения</option>
          <option value="solves_count">По числу решений</option>
          <option value="alphabetic">По алфавиту</option>
        </select>
      </div>
    </>
  )
}

function ScoringStep({ form, setField }) {
  const s = form.scoring_config
  const update = (patch) => setField('scoring_config', { ...s, ...patch })

  return (
    <>
      <h2>Очки</h2>
      <div className="wiz-field">
        <label>Режим</label>
        <select value={s.mode} onChange={(e) => update({ mode: e.target.value })}>
          <option value="fixed">Фиксированные</option>
          <option value="dynamic_decay">Динамические (decay)</option>
          <option value="placement">По местам (в конце)</option>
        </select>
      </div>

      <div className="wiz-field">
        <label>Дефолтные очки за задание</label>
        <input
          type="number"
          min="0"
          value={s.default_points}
          onChange={(e) => update({ default_points: Number(e.target.value) || 0 })}
        />
      </div>

      {s.mode === 'dynamic_decay' && (
        <div className="wiz-row-3">
          <div className="wiz-field">
            <label>Тип decay</label>
            <select
              value={s.dynamic_decay.decay_type}
              onChange={(e) =>
                update({
                  dynamic_decay: {
                    ...s.dynamic_decay,
                    decay_type: e.target.value,
                  },
                })
              }
            >
              <option value="step">Шаг</option>
              <option value="linear">Линейный</option>
              <option value="logarithmic">Логарифмический</option>
            </select>
          </div>
          <div className="wiz-field">
            <label>Макс. очков</label>
            <input
              type="number"
              min="0"
              value={s.dynamic_decay.max_points}
              onChange={(e) =>
                update({
                  dynamic_decay: {
                    ...s.dynamic_decay,
                    max_points: Number(e.target.value) || 0,
                  },
                })
              }
            />
          </div>
          <div className="wiz-field">
            <label>Мин. очков</label>
            <input
              type="number"
              min="0"
              value={s.dynamic_decay.min_points}
              onChange={(e) =>
                update({
                  dynamic_decay: {
                    ...s.dynamic_decay,
                    min_points: Number(e.target.value) || 0,
                  },
                })
              }
            />
          </div>
        </div>
      )}

      {s.mode === 'dynamic_decay' && (
        <div className="wiz-row-3">
          <div className="wiz-field">
            <label>Шаг снижения</label>
            <input
              type="number"
              min="0"
              value={s.dynamic_decay.decay_step}
              onChange={(e) =>
                update({
                  dynamic_decay: {
                    ...s.dynamic_decay,
                    decay_step: Number(e.target.value) || 0,
                  },
                })
              }
            />
          </div>
          <div className="wiz-field">
            <label>Интервал (кол-во решений)</label>
            <input
              type="number"
              min="1"
              value={s.dynamic_decay.decay_interval}
              onChange={(e) =>
                update({
                  dynamic_decay: {
                    ...s.dynamic_decay,
                    decay_interval: Number(e.target.value) || 1,
                  },
                })
              }
            />
          </div>
          <div className="wiz-field">
            <label>Когда считать</label>
            <select
              value="on_solve"
              disabled
              title="Динамический пересчёт — в следующей версии"
            >
              <option value="on_solve">При решении</option>
            </select>
          </div>
        </div>
      )}

      {s.mode === 'placement' && (
        <div className="wiz-field">
          <label>Места</label>
          <div
            className="mono"
            style={{ fontSize: 12, color: 'var(--text-faint)' }}
          >
            {s.placement.places.map((p) => `#${p.place} → ${p.points}`).join(' · ')}
          </div>
          <p style={{ fontSize: 12, color: 'var(--text-dim)' }}>
            Очки раздаются автоматически при завершении соревнования.
          </p>
        </div>
      )}

      <div className="wiz-field">
        <label>Штраф за подсказки</label>
        <label
          style={{
            fontFamily: 'inherit',
            textTransform: 'none',
            letterSpacing: 0,
          }}
        >
          <input
            type="checkbox"
            checked={!!s.hint_penalty.apply}
            onChange={(e) =>
              update({ hint_penalty: { apply: e.target.checked } })
            }
          />{' '}
          Вычитать стоимость подсказки из очков
        </label>
      </div>
    </>
  )
}

function InfraStep({ form, setField }) {
  const n = form.network_config
  const update = (patch) => setField('network_config', { ...n, ...patch })
  return (
    <>
      <h2>Инфраструктура</h2>
      <div className="wiz-row">
        <div className="wiz-field">
          <label>TTL инстанса (секунд)</label>
          <input
            type="number"
            min="60"
            value={form.instance_ttl_seconds}
            onChange={(e) => setField('instance_ttl_seconds', e.target.value)}
          />
        </div>
        <div className="wiz-field">
          <label>Макс. инстансов на пользователя</label>
          <input
            type="number"
            min="1"
            value={form.max_instances_per_user}
            onChange={(e) => setField('max_instances_per_user', e.target.value)}
          />
        </div>
      </div>
      <div className="wiz-row">
        <div className="wiz-field">
          <label>Макс. инстансов на команду</label>
          <input
            type="number"
            min="1"
            value={form.max_instances_per_team}
            onChange={(e) => setField('max_instances_per_team', e.target.value)}
          />
        </div>
        <div className="wiz-field">
          <label>Макс. инстансов на соревнование</label>
          <input
            type="number"
            min="1"
            value={form.max_instances_per_competition}
            onChange={(e) =>
              setField('max_instances_per_competition', e.target.value)
            }
          />
        </div>
      </div>
      <div className="wiz-row">
        <div className="wiz-field">
          <label>
            <input
              type="checkbox"
              checked={!!n.isolated}
              onChange={(e) => update({ isolated: e.target.checked })}
            />{' '}
            Изолированная сеть
          </label>
        </div>
        <div className="wiz-field">
          <label>
            <input
              type="checkbox"
              checked={!!n.allow_internet}
              onChange={(e) => update({ allow_internet: e.target.checked })}
            />{' '}
            Разрешить исходящий интернет
          </label>
        </div>
      </div>
    </>
  )
}

function ModeratorsStep({
  isNew,
  isAdmin,
  moderators,
  modUserId,
  setModUserId,
  modRole,
  setModRole,
  onAdd,
  onRemove,
  busy,
}) {
  if (isNew) {
    return (
      <>
        <h2>Модераторы</h2>
        <p style={{ color: 'var(--text-dim)' }}>
          Сначала создайте соревнование — потом можно назначать модераторов.
        </p>
      </>
    )
  }
  return (
    <>
      <h2>Модераторы</h2>
      <p style={{ color: 'var(--text-dim)', fontSize: 13 }}>
        Ответственные и помощники. Назначать может только администратор.
      </p>

      <div className="adm-table-wrap" style={{ marginBottom: 20 }}>
        <table className="adm-table">
          <thead>
            <tr>
              <th>user_id</th>
              <th>username</th>
              <th>роль</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {moderators.map((m) => (
              <tr key={m.user_id}>
                <td className="mono">#{m.user_id}</td>
                <td>{m.username}</td>
                <td className="mono">{m.role}</td>
                <td>
                  <button
                    className="adm-btn-mini danger"
                    disabled={busy || !isAdmin}
                    onClick={() => onRemove(m.user_id)}
                  >
                    Снять
                  </button>
                </td>
              </tr>
            ))}
            {moderators.length === 0 && (
              <tr>
                <td
                  colSpan={4}
                  className="mono"
                  style={{ color: 'var(--text-faint)' }}
                >
                  пока никого
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {isAdmin && (
        <div className="wiz-row">
          <div className="wiz-field">
            <label>user_id</label>
            <input
              type="number"
              value={modUserId}
              onChange={(e) => setModUserId(e.target.value)}
              placeholder="42"
            />
          </div>
          <div className="wiz-field">
            <label>Роль</label>
            <select value={modRole} onChange={(e) => setModRole(e.target.value)}>
              <option value="responsible">Ответственный</option>
              <option value="helper">Помощник</option>
            </select>
          </div>
        </div>
      )}
      {isAdmin && (
        <button
          className="btn btn-primary"
          disabled={busy || !modUserId}
          onClick={onAdd}
        >
          Назначить
        </button>
      )}
    </>
  )
}

function PublishStep({ isNew, form, isAdmin, onPublish, busy }) {
  if (isNew) {
    return (
      <>
        <h2>Публикация</h2>
        <p style={{ color: 'var(--text-dim)' }}>
          Сначала сохраните соревнование как черновик.
        </p>
      </>
    )
  }
  return (
    <>
      <h2>Публикация</h2>
      <p style={{ color: 'var(--text-dim)' }}>
        Текущий статус: <strong>{form.status}</strong>. Публикация переводит в{' '}
        <strong>announced</strong> — на этом шаге выделяется диапазон портов и
        создаётся Docker-сеть. Публиковать может только администратор.
      </p>
      <button
        className="btn btn-primary"
        disabled={busy || !isAdmin || form.status !== 'draft'}
        onClick={onPublish}
      >
        {busy ? 'Публикация…' : 'Опубликовать'}
      </button>
      {!isAdmin && (
        <p style={{ color: 'var(--danger)', fontSize: 12, marginTop: 8 }}>
          Публикация доступна только администратору.
        </p>
      )}
    </>
  )
}