import {Cockpit} from './Cockpit';
import {ReviewView} from './ReviewView';
import {SessionHome} from './SessionHome';
import {useReplayStore} from './store';
import './Replay.css';

export const ReplayPage: React.FC = () => {
  const session = useReplayStore((s) => s.session);
  const phase = useReplayStore((s) => s.phase);
  if (!session) return <SessionHome />;
  return (
    <div className="replay-page">
      {phase === 'review' ? <ReviewView /> : <Cockpit />}
    </div>
  );
};
