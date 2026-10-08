/**
 * WorkflowBar — 页头工作流条(Layout 统一挂载,页面零改动)。
 * 环节徽标 + 上下游直达;getFlowContext 为 null(无 stage 的路由)时不渲染。
 */
import {Link, useLocation} from 'react-router-dom';
import {getFlowContext} from '../config/navigation';
import './WorkflowBar.css';

export function WorkflowBar() {
  const location = useLocation();
  const flow = getFlowContext(location.pathname);
  if (!flow) return null;

  return (
    <nav className="wbar" aria-label="工作流位置">
      <span className="wbar__stage">{flow.stageTitle}</span>
      {flow.prev && (
        <Link className="wbar__link wbar__link--prev" to={flow.prev.path}>
          ← {flow.prev.label}
        </Link>
      )}
      {flow.next && (
        <Link className="wbar__link wbar__link--next" to={flow.next.path}>
          {flow.next.label} →
        </Link>
      )}
    </nav>
  );
}
