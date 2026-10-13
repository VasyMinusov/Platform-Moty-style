import './ErrorPage.css'

/**
 * Полноэкранная страница ошибки.
 *
 * Props:
 * - title    {string}  — крупный заголовок
 * - message  {string}  — пояснение
 * - error    {Error?}  — объект ошибки (для разработчика)
 * - onReset  {Function?} — колбэк "Попробовать снова" (для ErrorBoundary)
 * - showHome {boolean} — показывать ли кнопку "На главную" (по умолчанию true)
 */
export function ErrorPage({
  title = 'Что-то пошло не так',
  message = 'Произошла непредвиденная ошибка. Попробуйте обновить страницу.',
  error,
  onReset,
  showHome = true,
}) {
  return (
    <div className="error-page">
      <div className="error-page-card">
        <span className="error-page-code mono">error</span>
        <h1 className="error-page-title">{title}</h1>
        <p className="error-page-message">{message}</p>

        {error?.message && <pre className="error-page-detail mono">{String(error.message)}</pre>}

        <div className="error-page-actions">
          {onReset && (
            <button className="btn btn-primary" onClick={onReset}>
              Попробовать снова
            </button>
          )}
          {showHome && (
            <a className="btn" href="/">
              На главную
            </a>
          )}
        </div>
      </div>
    </div>
  )
}
