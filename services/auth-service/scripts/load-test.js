// ═══════════════════════════════════════════════════════════════════════════
// Нагрузочный тест для Auth Service (k6).
//
// Три сценария (запускаются параллельно):
//   1. login_success — 5 RPS, 1 мин. Успешный вход + refresh.
//   2. login_fail    — 5 RPS, 1 мин. Неверный пароль (rate limit + Argon2).
//   3. me            — 50 RPS, 1 мин. GET /users/me с access-токеном.
//
// Итого: ~60 RPS в среднем, ~3600 запросов за минуту.
//
// Использование:
//   k6 run scripts/load-test.js
//   BASE_URL=http://auth.example.com k6 run scripts/load-test.js
//
// Через Makefile:
//   make load-test
//
// Установка k6:
//   https://grafana.com/docs/k6/latest/set-up/install-k6/
//
// Интерпретация результатов:
//   - http_req_duration p(95) < 500ms — целевой SLA.
//   - http_req_failed < 5% — допустимо (login_fail ожидаемо даёт 401).
//   - auth_logins_total{result="success"} в /metrics — должно
//     коррелировать с итерациями login_success.
//
// ВАЖНО: rate limiter по умолчанию блокирует после 10 неудачных login
// на email. В login_fail используем разные email (по VU+ITER) — иначе
// после первой итерации весь VU получит 423 вместо 401.
// ═══════════════════════════════════════════════════════════════════════════

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter } from 'k6/metrics';

// ── Конфигурация ──────────────────────────────────────────────────────────
const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
const API = `${BASE_URL}/api/v1`;

const PASSWORD = 'correct horse battery staple nist';

// Кастомные счётчики — видны в summary, отличают разные исходы.
const loginSuccess = new Counter('login_success');
const loginFailure = new Counter('login_failure');
const meSuccess = new Counter('me_success');

// ── Опции ─────────────────────────────────────────────────────────────────
export const options = {
  scenarios: {
    // Успешный login: 5 RPS в течение 1 минуты.
    login_success: {
      executor: 'constant-arrival-rate',
      rate: 5,
      timeUnit: '1s',
      duration: '1m',
      preAllocatedVUs: 10,
      maxVUs: 30,
      exec: 'scenarioLoginSuccess',
      tags: { scenario: 'login_success' },
    },

    // Неудачный login: 5 RPS. Проверяет Argon2 (dummy verify) +
    // rate limiter под нагрузкой.
    login_fail: {
      executor: 'constant-arrival-rate',
      rate: 5,
      timeUnit: '1s',
      duration: '1m',
      preAllocatedVUs: 10,
      maxVUs: 30,
      exec: 'scenarioLoginFail',
      tags: { scenario: 'login_fail' },
    },

    // Авторизованные запросы: 50 RPS. Основная нагрузка на SQL +
    // валидацию JWT.
    me: {
      executor: 'constant-arrival-rate',
      rate: 50,
      timeUnit: '1s',
      duration: '1m',
      preAllocatedVUs: 50,
      maxVUs: 100,
      exec: 'scenarioMe',
      tags: { scenario: 'me' },
      startTime: '5s', // даём setup'у завершиться
    },
  },

  thresholds: {
    // SLA: 95-й перцентиль < 500ms, 99-й < 1s.
    'http_req_duration{scenario:login_success}': ['p(95)<500', 'p(99)<1000'],
    'http_req_duration{scenario:login_fail}':    ['p(95)<500', 'p(99)<1000'],
    'http_req_duration{scenario:me}':            ['p(95)<200', 'p(99)<500'],

    // login_fail ожидаемо даёт 401, поэтому общий http_req_failed
    // считаем мягко. Детальные проверки — в check() внутри сценариев.
    'http_req_failed': ['rate<0.10'],
  },
};

// ── Setup: подготовка тестового пользователя ──────────────────────────────
//
// k6 setup() выполняется ОДИН РАЗ до старта сценариев. Возвращает data,
// доступные в default/scenario-функциях через параметр `data`.
//
// Здесь:
//   1. Регистрируем уникального пользователя.
//   2. Логинимся — получаем access_token для сценария `me`.
//   3. Отдаём access_token и email сценариям.
export function setup() {
  // Уникальный email — чтобы повторные прогоны не падали на 409.
  const runId = `${Date.now()}-${Math.floor(Math.random() * 100000)}`;
  const email = `load-${runId}@example.com`;
  const username = `load_${runId.replace(/-/g, '_')}`;

  // 1. Регистрация.
  const registerRes = http.post(
    `${API}/auth/register`,
    JSON.stringify({ email, username, password: PASSWORD }),
    { headers: { 'Content-Type': 'application/json' } }
  );

  if (registerRes.status !== 201) {
    throw new Error(
      `setup: register failed: ${registerRes.status} ${registerRes.body}`
    );
  }

  // 2. Логин — получаем access + refresh.
  const loginRes = http.post(
    `${API}/auth/login`,
    JSON.stringify({ email, password: PASSWORD }),
    { headers: { 'Content-Type': 'application/json' } }
  );

  if (loginRes.status !== 200) {
    throw new Error(
      `setup: login failed: ${loginRes.status} ${loginRes.body}`
    );
  }

  const body = loginRes.json();
  return {
    email,
    accessToken: body.access_token,
    refreshToken: body.refresh_token,
    sessionId: body.session_id,
  };
}

// ── Сценарий 1: успешный login ────────────────────────────────────────────
//
// Использует email из setup — тот же пользователь логинится много раз.
// Каждый успешный login создаёт новую сессию (session_id разный),
// что нам и нужно для нагрузки.
export function scenarioLoginSuccess(data) {
  const res = http.post(
    `${API}/auth/login`,
    JSON.stringify({ email: data.email, password: PASSWORD }),
    {
      headers: { 'Content-Type': 'application/json' },
      tags: { endpoint: 'login_success' },
    }
  );

  const ok = check(res, {
    'login_success status is 200': (r) => r.status === 200,
    'login_success has access_token': (r) => {
      try {
        return !!r.json('access_token');
      } catch (e) {
        return false;
      }
    },
  });

  if (ok) {
    loginSuccess.add(1);
  }
}

// ── Сценарий 2: неудачный login ───────────────────────────────────────────
//
// Разные email на каждый запрос — иначе rate limiter залочит после
// 10 попыток на email, и вместо 401 начнём получать 423.
//
// VU и ITER берём из k6 runtime — уникальность гарантирована.
// Учитываем: Argon2id на dummy-хеше занимает 50–100 мс (memory-hard),
// поэтому VU может упереться в CPU раньше, чем в rate limiter.
export function scenarioLoginFail() {
  // Уникальный email: VU + ITER.
  const email = `fail-${__VU}-${__ITER}@example.com`;

  const res = http.post(
    `${API}/auth/login`,
    JSON.stringify({ email, password: 'wrong-password-attempt-12345' }),
    {
      headers: { 'Content-Type': 'application/json' },
      tags: { endpoint: 'login_fail' },
    }
  );

  // Ожидаем 401 (user_not_found) — это целевой исход.
  // 429/423 тоже валидны (rate limit сработал раньше).
  const ok = check(res, {
    'login_fail status is 401 or 429': (r) =>
      r.status === 401 || r.status === 429,
  });

  if (ok) {
    loginFailure.add(1);
  }
}

// ── Сценарий 3: GET /users/me ─────────────────────────────────────────────
//
// Основная нагрузка: валидация JWT + SELECT из БД.
// Использует access_token из setup.
export function scenarioMe(data) {
  const res = http.get(`${API}/users/me`, {
    headers: { Authorization: `Bearer ${data.accessToken}` },
    tags: { endpoint: 'me' },
  });

  const ok = check(res, {
    'me status is 200': (r) => r.status === 200,
    'me returns correct email': (r) => {
      try {
        return r.json('email') === data.email;
      } catch (e) {
        return false;
      }
    },
  });

  if (ok) {
    meSuccess.add(1);
  }
}

// ── Дефолтная функция ─────────────────────────────────────────────────────
//
// k6 вызывает default, если сценарий не указал exec. У нас все три
// сценария указывают exec явно — default не используется. Оставляем
// заглушку, чтобы k6 не ругался на отсутствие default.
export default function () {
  sleep(1);
}