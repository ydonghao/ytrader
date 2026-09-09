/**
 * ErrorBoundary — 捕获路由树渲染期异常。
 *
 * 之前 Indices / Backtest 单页崩溃会把整个 React root 卸载，只剩 body 背景
 * （近黑）→ "整屏黑屏"。本边界包住 <Routes> 后：侧边栏（在边界外）保持可点，
 * 内容区改为显示错误信息 + 重试，不再黑屏。
 *
 * App.tsx 中以 `key={location.pathname}` 渲染本组件，故切换到其它路由会自动挂载
 * 新实例（无 error 态）→ 自动恢复，无需手动刷新。
 */
import React from 'react';
import './ErrorBoundary.css';

interface Props {
  children: React.ReactNode;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends React.Component<Props, State> {
  state: State = {error: null};

  static getDerivedStateFromError(error: Error): State {
    return {error};
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    // eslint-disable-next-line no-console
    console.error('[ErrorBoundary]', error, info.componentStack);
  }

  private handleReset = () => this.setState({error: null});

  render() {
    if (!this.state.error) return this.props.children;
    const err = this.state.error;
    return (
      <div className="error-boundary">
        <div className="error-boundary__icon">△</div>
        <h2 className="error-boundary__title">页面渲染出错</h2>
        <p className="error-boundary__message">{err.message || String(err)}</p>
        {err.stack && <pre className="error-boundary__stack">{err.stack}</pre>}
        <div className="error-boundary__actions">
          <button className="error-boundary__btn" onClick={this.handleReset}>
            重试
          </button>
          <a className="error-boundary__btn error-boundary__btn--ghost" href="/">
            返回首页
          </a>
        </div>
        <p className="error-boundary__hint">
          可从左侧导航切换其它页面；若持续出错，请检查浏览器控制台或刷新。
        </p>
      </div>
    );
  }
}
