import { Component } from 'react'
import { ErrorPage } from './ErrorPage.jsx'

/**
 * Ловит ошибки рендера во вложенном дереве.
 *
 * В React 19 не появилось хук-версии для componentDidCatch — приходится
 * использовать класс. Это не «плохой код», это API React.
 *
 * Что делает:
 * 1. Ловит ошибку через getDerivedStateFromError.
 * 2. Логирует её в консоль через componentDidCatch.
 * 3. Показывает ErrorPage.
 * 4. Кнопка «Попробовать снова» сбрасывает состояние и перерисовывает детей.
 *
 * Что НЕ ловит (по дизайну React):
 * - ошибки в обработчиках событий (onClick и т.д.) — их надо ловить try/catch;
 * - ошибки в асинхронном коде (setTimeout, Promise) — тоже try/catch;
 * - ошибки в самом ErrorBoundary.
 */
export class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  componentDidCatch(error, errorInfo) {
    // eslint-disable-next-line no-console
    console.error('[ErrorBoundary] Перехвачена ошибка:', error, errorInfo)
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null })
  }

  render() {
    if (this.state.hasError) {
      return <ErrorPage error={this.state.error} onReset={this.handleReset} />
    }
    return this.props.children
  }
}
