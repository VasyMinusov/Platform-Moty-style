import { useQuery } from '@apollo/client';
import { GET_TASKS, GET_ME } from './graphql.js';

function TaskItem({ task }) {
  return (
    <li className={`task${task.done ? ' done' : ''}`}>
      <span className={`check${task.done ? ' on' : ''}`} aria-hidden="true">
        {task.done ? '✓' : ''}
      </span>
      <span className="title">{task.title}</span>
      <span className="badge">#{task.id}</span>
    </li>
  );
}

function EmptyState({ loading }) {
  if (loading) {
    return (
      <div className="empty">
        <span className="spinner" />
        <span>Загрузка…</span>
      </div>
    );
  }
  return (
    <div className="empty">
      <span>Задач пока нет.</span>
    </div>
  );
}

export default function App() {
  const { data: meData } = useQuery(GET_ME);
  const { data, loading, error } = useQuery(GET_TASKS);

  const tasks = data?.tasks ?? [];
  const done = tasks.filter(t => t.done).length;
  const total = tasks.length;

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo" aria-hidden="true">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
              <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="1.8" />
              <path d="M8 12.5l2.5 2.5L16 9.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </span>
          <span className="brand-name">Ordo Tasks</span>
        </div>

        <div className="user">
          {meData?.me ? (
            <>
              <span className="avatar" aria-hidden="true">
                {meData.me.username.slice(0, 1).toUpperCase()}
              </span>
              <span className="username">{meData.me.username}</span>
            </>
          ) : (
            <span className="username muted">…</span>
          )}
        </div>
      </header>

      <main className="main">
        <section className="hero">
          <h1>Мои задачи</h1>
          <p className="subtitle">
            {total > 0
              ? `Выполнено ${done} из ${total}`
              : 'Внутренний таск-трекер команды'}
          </p>
        </section>

        {error && (
          <div className="alert">
            Ошибка загрузки задач: {error.message}
          </div>
        )}

        <section className="card">
          {tasks.length === 0 ? (
            <EmptyState loading={loading} />
          ) : (
            <ul className="task-list">
              {tasks.map(t => (
                <TaskItem key={t.id} task={t} />
              ))}
            </ul>
          )}
        </section>

        <footer className="foot">
          <span>Ordo Tasks · internal</span>
        </footer>
      </main>
    </div>
  );
}