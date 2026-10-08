/** 触发式 AI 任务状态机（AiInsightPanel 配套） */
export type AiTaskState = {status: 'idle' | 'loading' | 'error'; error?: string};

export type AiTaskAction =
  | {type: 'start'}
  | {type: 'done'}
  | {type: 'fail'; error: string}
  | {type: 'reset'};

export function aiTaskReducer(state: AiTaskState, action: AiTaskAction): AiTaskState {
  switch (action.type) {
    case 'start': return {status: 'loading'};
    case 'done': return {status: 'idle'};
    case 'fail': return {status: 'error', error: action.error};
    case 'reset': return {status: 'idle'};
  }
}
