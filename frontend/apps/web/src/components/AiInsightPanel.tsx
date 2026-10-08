/**
 * AiInsightPanel — 嵌入式 AI 面板统一外壳。
 * 统一标题行(标题+AI徽标+操作槽)/加载骨架/错误卡(带重试)/内容槽。
 * AI 是功能不是页面:各页 AI 面板以此壳渲染,配置统一走后端 llm_config。
 */
import React from 'react';
import './AiInsightPanel.css';

interface Props {
  title: string;
  /** 来源标注(如 glm-5.3 / AI 基本面),展示在标题右侧 */
  source?: string;
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  /** 标题行右侧操作槽(如"生成初稿"按钮) */
  actions?: React.ReactNode;
  children: React.ReactNode;
}

export function AiInsightPanel({title, source, loading, error, onRetry, actions, children}: Props) {
  return (
    <section className="ai-panel">
      <header className="ai-panel__head">
        <h3 className="ai-panel__title">
          ✦ {title}
          {source && <span className="ai-panel__source">{source}</span>}
        </h3>
        {actions && <div className="ai-panel__actions">{actions}</div>}
      </header>
      {loading && (
        <div className="ai-panel__loading" role="status">
          <span className="ui-state__spinner" /> AI 生成中,长文可能需要一两分钟…
        </div>
      )}
      {!loading && error && (
        <div className="ai-panel__error">
          <span>{error}</span>
          {onRetry && (
            <button className="ai-panel__retry" onClick={onRetry}>重试</button>
          )}
        </div>
      )}
      {!loading && !error && <div className="ai-panel__body">{children}</div>}
    </section>
  );
}
