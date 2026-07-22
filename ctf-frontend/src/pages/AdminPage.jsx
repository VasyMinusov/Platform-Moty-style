import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import './AdminPage.css'

function ActionCard({ eyebrow, title, description, actionLabel, busyLabel, onRun }) {
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  async function run() {
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      const data = await onRun()
      setResult(data)
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setError('Доступ только для администраторов платформы.')
      } else {
        setError(err instanceof ApiError ? err.message : 'Операция не выполнена')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="admin-card">
      <span className="eyebrow">{eyebrow}</span>
      <h3>{title}</h3>
      <p>{description}</p>

      {error && <div className="alert">{error}</div>}
      {result && (
        <div className="alert alert-success mono">{JSON.stringify(result)}</div>
      )}

      <button className="btn btn-primary" onClick={run} disabled={busy}>
        {busy ? busyLabel : actionLabel}
      </button>
    </div>
  )
}

export default function AdminPage() {
  return (
    <div>
      <div className="page-head">
        <div>
          <span className="eyebrow">служебный контур</span>
          <h1>Администрирование</h1>
        </div>
      </div>

      <p className="admin-note">
        Действия ниже доступны только пользователям с ролью <code className="mono">admin</code>.
        Если ваша учётная запись обычная — сервер ответит ошибкой доступа.
      </p>

      <div className="admin-grid">
        <ActionCard
          eyebrow="реестр заданий"
          title="Синхронизировать задания"
          description="Пересканировать папку с заданиями и обновить записи в базе данных платформы. Нужно после добавления новой папки задания на сервере."
          actionLabel="Запустить синхронизацию"
          busyLabel="Сканирование…"
          onRun={api.syncChallenges}
        />
        <ActionCard
          eyebrow="контейнеры"
          title="Очистить просроченные инстансы"
          description="Остановить и удалить контейнеры заданий, у которых истёк TTL. В проде эту операцию стоит запускать по расписанию."
          actionLabel="Запустить очистку"
          busyLabel="Очистка…"
          onRun={api.reapInstances}
        />
        <div className="admin-card">
          <span className="eyebrow">персонал</span>
          <h3>Пользователи</h3>
          <p>Статусы участников (отображаются как #статус), блокировка и разблокировка аккаунтов, назначение ролей student / moderator / admin.</p>
          <Link to="/users" className="btn btn-primary">
            Управление пользователями
          </Link>
        </div>
        <div className="admin-card">
          <span className="eyebrow">база знаний</span>
          <h3>Write-ups</h3>
          <p>Управление решениями заданий: добавление, редактирование и удаление пошаговых write-ups в формате JSON.</p>
          <Link to="/admin/writeups" className="btn btn-primary">
            Перейти к write-ups
          </Link>
        </div>
        <div className="admin-card">
          <span className="eyebrow">библиотека</span>
          <h3>Занятия</h3>
          <p>Библиотека учебных статей в Markdown: создание и редактирование занятий (доступно также модераторам).</p>
          <Link to="/lessons" className="btn btn-primary">
            Перейти к занятиям
          </Link>
        </div>
      </div>
    </div>
  )
}

