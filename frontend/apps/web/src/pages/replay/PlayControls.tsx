import {useEffect} from 'react';
import {useReplayStore} from './store';

export const PlayControls: React.FC = () => {
  const playing = useReplayStore((s) => s.playing);
  const speed = useReplayStore((s) => s.speed);
  const cursor = useReplayStore((s) => s.cursor);
  const datesLen = useReplayStore((s) => s.dates.length);
  const {advance, stepBack, play, pause, setSpeed} = useReplayStore.getState();

  useEffect(() => {
    if (!playing) return;
    const t = setInterval(() => {
      void useReplayStore.getState().advance();
    }, 1000 / speed);
    return () => clearInterval(t);
  }, [playing, speed]);

  const atReview = cursor < datesLen - 1;
  return (
    <div className="replay-panel replay-controls">
      <button className="replay-btn" disabled={cursor <= 0}
        onClick={stepBack} title="回看一天（只看不许交易）">
        ◀
      </button>
      <button className="replay-btn primary"
        onClick={() => void advance()}>
        下一天 ▶
      </button>
      <button className="replay-btn"
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
