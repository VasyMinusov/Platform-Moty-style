const BASE_URL = import.meta.env.VITE_API_URL || '/api'

export class ApiError extends Error {
  constructor(message, status, detail) {
    super(message)
    this.status = status
    this.detail = detail
  }
}

function getToken() {
  return localStorage.getItem('ctf_token')
}

export async function apiFetch(path, { method = 'GET', body, headers, skipAuth = false } = {}) {
  const finalHeaders = { ...headers }
  let finalBody = body

  if (body !== undefined && !(body instanceof URLSearchParams) && !(body instanceof FormData)) {
    finalHeaders['Content-Type'] = 'application/json'
    finalBody = JSON.stringify(body)
  } else if (body instanceof URLSearchParams) {
    finalHeaders['Content-Type'] = 'application/x-www-form-urlencoded'
  }

  const token = getToken()
  if (token && !skipAuth) {
    finalHeaders['Authorization'] = `Bearer ${token}`
  }

  let response
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      method,
      headers: finalHeaders,
      body: finalBody,
    })
  } catch (networkErr) {
    throw new ApiError('Не удалось связаться с сервером платформы', 0, null)
  }

  if (response.status === 204) return null

  let data = null
  const text = await response.text()
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = null
    }
  }

  if (!response.ok) {
    if (response.status === 401 && !skipAuth) {
      localStorage.removeItem('ctf_token')
      localStorage.removeItem('ctf_username')
      localStorage.removeItem('ctf_role')
      if (!window.location.pathname.startsWith('/login')) {
        window.location.assign('/login')
      }
    }
    const detail = data?.detail
    const message = Array.isArray(detail)
      ? detail.map((d) => d.msg).join('; ')
      : detail || `Ошибка запроса (${response.status})`
    throw new ApiError(message, response.status, detail)
  }

  return data
}

/**
 * Скачивает файл с авторизацией. Возвращает Blob.
 * Используется, когда нужно отдать файл браузеру с Bearer-токеном.
 */
export async function downloadFile(path) {
  const token = getToken()
  const headers = {}
  if (token) headers['Authorization'] = `Bearer ${token}`

  const response = await fetch(`${BASE_URL}${path}`, { headers })
  if (!response.ok) {
    let detail = null
    try {
      detail = (await response.json()).detail
    } catch {
      /* ignore */
    }
    throw new ApiError(
      detail || `Ошибка скачивания (${response.status})`,
      response.status,
      detail,
    )
  }
  return response.blob()
}

/**
 * Скачивает файл и сохраняет его через <a download>.
 */
export async function downloadAndSave(path, filename) {
  const blob = await downloadFile(path)
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename || 'download'
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export const api = {
  // ── Auth ──
  register: (payload) =>
    apiFetch('/auth/register', { method: 'POST', body: payload, skipAuth: true }),
  login: (username, password) => {
    const form = new URLSearchParams()
    form.set('username', username)
    form.set('password', password)
    return apiFetch('/auth/login', { method: 'POST', body: form, skipAuth: true })
  },
  me: () => apiFetch('/auth/me'),

  // ── Задания (глобальные) ──
  listChallenges: () => apiFetch('/challenges'),
  startChallenge: (slug) => apiFetch(`/challenges/${slug}/start`, { method: 'POST' }),
  stopChallenge: (slug) => apiFetch(`/challenges/${slug}/stop`, { method: 'POST' }),
  submitFlag: (slug, flag) =>
    apiFetch(`/challenges/${slug}/submit`, { method: 'POST', body: { flag } }),

  // ── Админ (глобальный) ──
  syncChallenges: () => apiFetch('/admin/challenges/sync', { method: 'POST' }),
  reapInstances: () => apiFetch('/admin/instances/reap', { method: 'POST' }),
  listUsers: () => apiFetch('/admin/users'),
  updateUser: (id, payload) =>
    apiFetch(`/admin/users/${id}`, { method: 'PATCH', body: payload }),
  setUserRole: (id, role) =>
    apiFetch(`/admin/users/${id}/role`, { method: 'PUT', body: { role } }),

  // ── Библиотека занятий ──
  listLessons: () => apiFetch('/lessons'),
  getLesson: (slug) => apiFetch(`/lessons/${slug}`),
  createLesson: (payload) =>
    apiFetch('/lessons', { method: 'POST', body: payload }),
  updateLesson: (slug, payload) =>
    apiFetch(`/lessons/${slug}`, { method: 'PUT', body: payload }),
  deleteLesson: (slug) => apiFetch(`/lessons/${slug}`, { method: 'DELETE' }),

  // ── Write-ups ──
  listWriteups: () => apiFetch('/writeups'),
  getWriteup: (slug) => apiFetch(`/writeups/${slug}`),
  createWriteup: (payload) =>
    apiFetch('/writeups', { method: 'POST', body: payload }),
  updateWriteup: (slug, payload) =>
    apiFetch(`/writeups/${slug}`, { method: 'PUT', body: payload }),
  deleteWriteup: (slug) => apiFetch(`/writeups/${slug}`, { method: 'DELETE' }),

  // ══════════════════════════════════════════════════════════════════
  // Соревнования: публичное / участническое
  // ══════════════════════════════════════════════════════════════════

  listCompetitions: (params = {}) => {
    const qs = new URLSearchParams()
    if (params.status) qs.set('status', params.status)
    if (params.visibility) qs.set('visibility', params.visibility)
    const suffix = qs.toString() ? `?${qs}` : ''
    return apiFetch(`/competitions${suffix}`)
  },
  getCompetition: (slug) => apiFetch(`/competitions/${slug}`),
  applyToCompetition: (slug, payload = {}) =>
    apiFetch(`/competitions/${slug}/apply`, { method: 'POST', body: payload }),
  withdrawFromCompetition: (slug) =>
    apiFetch(`/competitions/${slug}/apply`, { method: 'DELETE' }),
  getMyApplication: (slug) => apiFetch(`/competitions/${slug}/my-application`),

  // Задания соревнования
  listCompetitionChallenges: (slug) => apiFetch(`/competitions/${slug}/challenges`),
  getCompetitionChallenge: (slug, chSlug) =>
    apiFetch(`/competitions/${slug}/challenges/${chSlug}`),
  startCompetitionChallenge: (slug, chSlug) =>
    apiFetch(`/competitions/${slug}/challenges/${chSlug}/start`, { method: 'POST' }),
  stopCompetitionChallenge: (slug, chSlug) =>
    apiFetch(`/competitions/${slug}/challenges/${chSlug}/stop`, { method: 'POST' }),
  submitCompetitionFlag: (slug, chSlug, flag) =>
    apiFetch(`/competitions/${slug}/challenges/${chSlug}/submit`, {
      method: 'POST',
      body: { flag },
    }),
  buyHint: (slug, chSlug, hintIndex) =>
    apiFetch(`/competitions/${slug}/challenges/${chSlug}/hints/${hintIndex}/buy`, {
      method: 'POST',
    }),
  listPurchasedHints: (slug, chSlug) =>
    apiFetch(`/competitions/${slug}/challenges/${chSlug}/hints/purchased`),

  // Leaderboard
  getLeaderboard: (slug) => apiFetch(`/competitions/${slug}/leaderboard`),

  // Команды
  listTeams: (slug) => apiFetch(`/competitions/${slug}/teams`),
  getTeam: (slug, teamId) => apiFetch(`/competitions/${slug}/teams/${teamId}`),
  getMyTeam: (slug) => apiFetch(`/competitions/${slug}/my-team`),
  getMyInvitations: (slug) => apiFetch(`/competitions/${slug}/my-invitations`),
  createTeam: (slug, name) =>
    apiFetch(`/competitions/${slug}/teams`, { method: 'POST', body: { name } }),
  renameTeam: (slug, teamId, name) =>
    apiFetch(`/competitions/${slug}/teams/${teamId}`, {
      method: 'PATCH',
      body: { name },
    }),
  disbandTeam: (slug, teamId) =>
    apiFetch(`/competitions/${slug}/teams/${teamId}`, { method: 'DELETE' }),
  inviteToTeam: (slug, teamId, username) =>
    apiFetch(`/competitions/${slug}/teams/${teamId}/invite`, {
      method: 'POST',
      body: { username },
    }),
  acceptInvite: (slug, teamId) =>
    apiFetch(`/competitions/${slug}/teams/${teamId}/invite/accept`, { method: 'POST' }),
  declineInvite: (slug, teamId) =>
    apiFetch(`/competitions/${slug}/teams/${teamId}/invite/decline`, { method: 'POST' }),
  joinByCode: (slug, invite_code) =>
    apiFetch(`/competitions/${slug}/teams/join-by-code`, {
      method: 'POST',
      body: { invite_code },
    }),
  kickMember: (slug, teamId, userId) =>
    apiFetch(`/competitions/${slug}/teams/${teamId}/members/${userId}`, {
      method: 'DELETE',
    }),
  leaveTeam: (slug, teamId) =>
    apiFetch(`/competitions/${slug}/teams/${teamId}/leave`, { method: 'POST' }),

  // Апелляции (участник)
  createAppeal: (slug, payload) =>
    apiFetch(`/competitions/${slug}/appeals`, { method: 'POST', body: payload }),
  listMyAppeals: (slug) => apiFetch(`/competitions/${slug}/my-appeals`),

  // ══════════════════════════════════════════════════════════════════
  // Соревнования: админ
  // ══════════════════════════════════════════════════════════════════

  adminListCompetitions: (params = {}) => {
    const qs = new URLSearchParams()
    if (params.status) qs.set('status', params.status)
    if (params.only_mine) qs.set('only_mine', 'true')
    const suffix = qs.toString() ? `?${qs}` : ''
    return apiFetch(`/admin/competitions${suffix}`)
  },
  adminGetCompetition: (slug) => apiFetch(`/admin/competitions/${slug}`),
  adminCreateCompetition: (payload) =>
    apiFetch('/admin/competitions', { method: 'POST', body: payload }),
  adminUpdateCompetition: (slug, payload) =>
    apiFetch(`/admin/competitions/${slug}`, { method: 'PATCH', body: payload }),
  adminDeleteCompetition: (slug) =>
    apiFetch(`/admin/competitions/${slug}`, { method: 'DELETE' }),

  adminPublishCompetition: (slug) =>
    apiFetch(`/admin/competitions/${slug}/publish`, { method: 'POST' }),
  adminOpenRegistration: (slug) =>
    apiFetch(`/admin/competitions/${slug}/open-registration`, { method: 'POST' }),
  adminCloseRegistration: (slug) =>
    apiFetch(`/admin/competitions/${slug}/close-registration`, { method: 'POST' }),
  adminStartCompetition: (slug) =>
    apiFetch(`/admin/competitions/${slug}/start`, { method: 'POST' }),
  adminPauseCompetition: (slug) =>
    apiFetch(`/admin/competitions/${slug}/pause`, { method: 'POST' }),
  adminResumeCompetition: (slug) =>
    apiFetch(`/admin/competitions/${slug}/resume`, { method: 'POST' }),
  adminFinishCompetition: (slug) =>
    apiFetch(`/admin/competitions/${slug}/finish`, { method: 'POST' }),
  adminCancelCompetition: (slug) =>
    apiFetch(`/admin/competitions/${slug}/cancel`, { method: 'POST' }),

  adminListModerators: (slug) => apiFetch(`/admin/competitions/${slug}/moderators`),
  adminAddModerator: (slug, payload) =>
    apiFetch(`/admin/competitions/${slug}/moderators`, {
      method: 'POST',
      body: payload,
    }),
  adminRemoveModerator: (slug, userId) =>
    apiFetch(`/admin/competitions/${slug}/moderators/${userId}`, {
      method: 'DELETE',
    }),

  adminListApplications: (slug, status) => {
    const qs = status ? `?status=${status}` : ''
    return apiFetch(`/admin/competitions/${slug}/applications${qs}`)
  },
  adminDecideApplication: (slug, appId, payload) =>
    apiFetch(`/admin/competitions/${slug}/applications/${appId}`, {
      method: 'PATCH',
      body: payload,
    }),

  adminListChallenges: (slug) => apiFetch(`/admin/competitions/${slug}/challenges`),
  adminGetChallenge: (slug, chSlug) =>
    apiFetch(`/admin/competitions/${slug}/challenges/${chSlug}`),
  adminUploadChallenge: (slug, file) => {
    const form = new FormData()
    form.append('file', file)
    return apiFetch(`/admin/competitions/${slug}/challenges/upload`, {
      method: 'POST',
      body: form,
    })
  },
  adminUpdateChallenge: (slug, chSlug, payload) =>
    apiFetch(`/admin/competitions/${slug}/challenges/${chSlug}`, {
      method: 'PATCH',
      body: payload,
    }),
  adminDeleteChallenge: (slug, chSlug) =>
    apiFetch(`/admin/competitions/${slug}/challenges/${chSlug}`, {
      method: 'DELETE',
    }),
  adminRebuildChallenge: (slug, chSlug) =>
    apiFetch(`/admin/competitions/${slug}/challenges/${chSlug}/rebuild`, {
      method: 'POST',
    }),
  adminBuildStatus: (slug, chSlug) =>
    apiFetch(`/admin/competitions/${slug}/challenges/${chSlug}/build-status`),
  adminPromoteChallenge: (slug, chSlug, payload) =>
    apiFetch(`/admin/competitions/${slug}/challenges/${chSlug}/promote`, {
      method: 'POST',
      body: payload,
    }),

  adminListTeams: (slug) => apiFetch(`/competitions/${slug}/teams`),

  adminGetDashboard: (slug) => apiFetch(`/admin/competitions/${slug}/dashboard`),
  adminScoreAdjust: (slug, payload) =>
    apiFetch(`/admin/competitions/${slug}/score-adjust`, {
      method: 'POST',
      body: payload,
    }),

  adminListAppeals: (slug, status) => {
    const qs = status ? `?status=${status}` : ''
    return apiFetch(`/admin/competitions/${slug}/appeals${qs}`)
  },
  adminResolveAppeal: (slug, appealId, payload) =>
    apiFetch(`/admin/competitions/${slug}/appeals/${appealId}`, {
      method: 'PATCH',
      body: payload,
    }),

  // ══════════════════════════════════════════════════════════════════
  // Уведомления
  // ══════════════════════════════════════════════════════════════════

  listNotifications: ({ limit = 50, offset = 0, unread_only = false } = {}) => {
    const qs = new URLSearchParams()
    qs.set('limit', String(limit))
    qs.set('offset', String(offset))
    if (unread_only) qs.set('unread_only', 'true')
    return apiFetch(`/notifications?${qs}`)
  },
  markNotificationRead: (id) =>
    apiFetch(`/notifications/${id}/read`, { method: 'POST' }),
  markAllNotificationsRead: () =>
    apiFetch('/notifications/read-all', { method: 'POST' }),
  deleteNotification: (id) =>
    apiFetch(`/notifications/${id}`, { method: 'DELETE' }),
  clearNotifications: () => apiFetch('/notifications', { method: 'DELETE' }),
}