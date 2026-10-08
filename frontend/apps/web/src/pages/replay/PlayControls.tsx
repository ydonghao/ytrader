import {useEffect} from 'react';
import {useReplayStore} from './store';

export const PlayControls: React.FC = () => {
  const playing = useReplayStore((s) => s.playing);
  const speed = useReplayStore((s) => s.speed);
  const cursor = useReplayStore((s) => s.cursor);
  const datesLen = useReplayStore((s) => s.dates.length);
  const mode = useReplayStore((s) => s.mode);
  const segIdx = useReplayStore((s) => s.segIdx);
  const segCount = useReplayStore((s) => s.segCount);
  const travelComplete = useReplayStore((s) => s.travelComplete);
  const {advance, stepBack, play, pause, setSpeed} =
    useReplayStore.getState();

  useEffect(() => {
    if (!playing) return;
    const t = setInterval(() => {
      void useReplayStore.getState().advance();
    }, 1000 / speed);
    return () => clearInterval(t);
  }, [playing, speed]);

  const atReview = cursor < datesLen - 1;
  const exam = mode === 'exam';
  return (
    <div className="replay-panel replay-controls">
      <button className="replay-btn" disabled={cursor <= 0}
        onClick={stepBack} title="回看一天（只看不许交易）">
        ◀
      </button>
      <button className="replay-btn primary"
        disabled={travelComplete}
        onClick={() => void advance(exam ? 'seg' : undefined)}>
        {exam ? `下一时段 ▶ (${segIdx + 1}/${segCount})` : '下一天 ▶'}
      </button>
      {exam && (
        <button className="replay-btn" disabled={travelComplete}
          title="快进:走完今日剩余时段(挂单照常检查),跳到明日开盘"
          onClick={() => void advance('day')}>
          快进到明日 ⏭
        </button>
      )}
      <button className="replay-btn"
        disabled={travelComplete}
        onClick={() => (playing ? pause() : play())}>
        {playing ? '⏸ 暂停' : '▶ 自动'}
      </button>
      {([1, 2, 4] as const).map((v) => (
        <button key={v}
          className={`replay-btn${speed === v ? ' primary' : ''}`}
          onClick={() => setSpeed(v)}>
          {v}x
        </button>
      ))}
      {atReview && <span className="replay-hint">回看中（不可交易）</span>}
    </div>
  );
};
