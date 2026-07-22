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

  if (body !== undefined && !(body instanceof URLSearchParams)) {
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

export const api = {
  register: (payload) => apiFetch('/auth/register', { method: 'POST', body: payload, skipAuth: true }),
  login: (username, password) => {
    const form = new URLSearchParams()
    form.set('username', username)
    form.set('password', password)
    return apiFetch('/auth/login', { method: 'POST', body: form, skipAuth: true })
  },
  me: () => apiFetch('/auth/me'),
  listChallenges: () => apiFetch('/challenges'),
  startChallenge: (slug) => apiFetch(`/challenges/${slug}/start`, { method: 'POST' }),
  stopChallenge: (slug) => apiFetch(`/challenges/${slug}/stop`, { method: 'POST' }),
  submitFlag: (slug, flag) => apiFetch(`/challenges/${slug}/submit`, { method: 'POST', body: { flag } }),
  syncChallenges: () => apiFetch('/admin/challenges/sync', { method: 'POST' }),
  reapInstances: () => apiFetch('/admin/instances/reap', { method: 'POST' }),
  // Пользователи (admin — управление, moderator — просмотр)
  listUsers: () => apiFetch('/admin/users'),
  updateUser: (id, payload) => apiFetch(`/admin/users/${id}`, { method: 'PATCH', body: payload }),
  setUserRole: (id, role) => apiFetch(`/admin/users/${id}/role`, { method: 'PUT', body: { role } }),
  // Библиотека занятий
  listLessons: () => apiFetch('/lessons'),
  getLesson: (slug) => apiFetch(`/lessons/${slug}`),
  createLesson: (payload) => apiFetch('/lessons', { method: 'POST', body: payload }),
  updateLesson: (slug, payload) => apiFetch(`/lessons/${slug}`, { method: 'PUT', body: payload }),
  deleteLesson: (slug) => apiFetch(`/lessons/${slug}`, { method: 'DELETE' }),
  // Write-ups
  listWriteups: () => apiFetch('/writeups'),
  getWriteup: (slug) => apiFetch(`/writeups/${slug}`),
  createWriteup: (payload) => apiFetch('/writeups', { method: 'POST', body: payload }),
  updateWriteup: (slug, payload) => apiFetch(`/writeups/${slug}`, { method: 'PUT', body: payload }),
  deleteWriteup: (slug) => apiFetch(`/writeups/${slug}`, { method: 'DELETE' }),
}

