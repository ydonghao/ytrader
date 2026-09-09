/**
 * SystemLogs — read-only system log viewer.
 *
 * Left panel lists every *.log file under backend/logs/. The toolbar lets the
 * user filter by date (parsed from the in-line timestamp of each line) and by
 * level. "实时跟随" (live follow) streams new lines over SSE — only enabled when
 * no date filter is set (you can't live-follow history).
 */
import React, {useState, useEffect, useCallback, useRef} from 'react';
import {getApiBase} from '../lib/api';
import {Icons} from '../components/icons';
import './SystemLogs.css';

const API_BASE = getApiBase();
const MAX_LINES = 5000;
// 渲染窗口：缓冲区可保留 MAX_LINES 行，但只渲染最近 RENDER_WINDOW 行到 DOM，
// 避免数千个 DOM 节点导致滚动/重绘卡顿（无需引入虚拟化依赖）。
const RENDER_WINDOW = 800;
const LEVELS = ['', 'DEBUG', 'INFO', 'WARNING', 'ERROR'];

interface LogFile {
  name: string;
  size_bytes: number;
  size_human: string;
  mtime: string;
}

interface ContentResp {
  file: string;
  lines: string[];
  matched: number;
  shown: number;
  truncated: boolean;
  total_lines: number;
  size_bytes: number;
  mtime: string;
}

/** Detect log level from a line's tokens for coloring. */
function lineLevel(line: string): string {
  if (/\bERROR\b|\bCRITICAL\b/.test(line)) return 'ERROR';
  if (/\bWARNING\b|\bWARN\b/.test(line)) return 'WARNING';
  if (/\bDEBUG\b/.test(line)) return 'DEBUG';
  return 'INFO';
}

export const SystemLogs: React.FC = () => {
  const [files, setFiles] = useState<LogFile[]>([]);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [lines, setLines] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [date, setDate] = useState<string>('');           // '' = latest / live
  const [level, setLevel] = useState<string>('');
  const [follow, setFollow] = useState<boolean>(true);    // live SSE tail

  const [meta, setMeta] = useState<{matched: number; shown: number; truncated: boolean; total: number} | null>(null);
  const [autoScroll, setAutoScroll] = useState(true);

  const scrollRef = useRef<HTMLDivElement>(null);
  const esRef = useRef<EventSource | null>(null);
  const lineCountRef = useRef(0);

  /* ── Load file list ── */
  const loadFiles = useCallback(async () => {
    try {
      const r = await fetch(`${API_BASE}/logs/files`);
      const j = await r.json();
      if (j.code === 0) {
        setFiles(j.data || []);
        if ((j.data?.length ?? 0) > 0 && !selectedFile) {
          setSelectedFile(j.data[0].name);
        }
      } else {
        setError(j.msg || `加载失败 (code=${j.code})`);
      }
    } catch {
      setError('无法连接后端，请确认后端服务已启动');
    }
  }, [selectedFile]);

  useEffect(() => { loadFiles(); }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  /* ── Static fetch (history date, or live disabled) ── */
  const fetchStatic = useCallback(async (file: string) => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({file, tail: String(1000)});
      if (date) params.set('date', date);
      if (level) params.set('level', level);
      const r = await fetch(`${API_BASE}/logs/content?${params}`);
      const j = await r.json();
      if (j.code === 0) {
        const d: ContentResp = j.data;
        setLines(d.lines);
        lineCountRef.current = d.lines.length;
        setMeta({matched: d.matched, shown: d.shown, truncated: d.truncated, total: d.total_lines});
      } else {
        setError(j.msg || '读取失败');
        setLines([]);
        setMeta(null);
      }
    } catch (e: any) {
      setError(e.message || '读取失败');
      setLines([]);
      setMeta(null);
    } finally {
      setLoading(false);
    }
  }, [date, level]);

  /* ── Live SSE follow (only when no date filter) ── */
  const startStream = useCallback((file: string) => {
    stopStream();
    const params = new URLSearchParams({file, tail: '200'});
    const es = new EventSource(`${API_BASE}/logs/stream?${params}`);
    esRef.current = es;
    const buffer: string[] = [];
    es.onmessage = (ev) => {
      try {
        const j = JSON.parse(ev.data);
        if (j?.data?.line != null) {
          buffer.push(j.data.line);
          // flush in batches to avoid per-line React churn
        }
      } catch {/* ignore malformed */}
    };
    es.onerror = () => { /* EventSource auto-reconnects */ };
    // flush loop
    const timer = window.setInterval(() => {
      if (buffer.length === 0) return;
      const batch = buffer.splice(0, buffer.length);
      setLines(prev => {
        const next = prev.concat(batch);
        return next.length > MAX_LINES ? next.slice(next.length - MAX_LINES) : next;
      });
      lineCountRef.current += batch.length;
    }, 300);
    (es as any)._timer = timer;
  }, []);

  const stopStream = useCallback(() => {
    if (esRef.current) {
      const t = (esRef.current as any)._timer;
      if (t) window.clearInterval(t);
      esRef.current.close();
      esRef.current = null;
    }
  }, []);

  // Re-load whenever selection / filters change.
  useEffect(() => {
    if (!selectedFile) { setLines([]); setMeta(null); return; }
    const live = follow && !date;
    if (live) {
      setLoading(true);
      // seed with a static tail, then stream
      fetchStatic(selectedFile).finally(() => setLoading(false));
      startStream(selectedFile);
    } else {
      stopStream();
      fetchStatic(selectedFile);
    }
    return () => { /* stream closed in its own effect */ };
  }, [selectedFile, follow, date, level]);  // eslint-disable-line react-hooks/exhaustive-deps

  // Close SSE on unmount.
  useEffect(() => () => stopStream(), [stopStream]);

  /* ── Auto-scroll to bottom when new lines arrive ── */
  useEffect(() => {
    if (!autoScroll || !scrollRef.current) return;
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [lines, autoScroll]);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
    setAutoScroll(atBottom);
  };

  /* ── Live state: only valid when following today ── */
  const isLive = follow && !date && !!selectedFile;

  return (
    <div className="syslogs">
      <header className="syslogs__header">
        <h1 className="syslogs__title">
          <span className="syslogs__title-icon">{Icons.terminal}</span>
          系统日志
        </h1>
        <div className="syslogs__toolbar">
          <label className="syslogs__field">
            <span className="syslogs__field-label">日期</span>
            <input
              type="date"
              className="syslogs__date-input"
              value={date}
              onChange={e => setDate(e.target.value)}
            />
          </label>
          <label className="syslogs__field">
            <span className="syslogs__field-label">级别</span>
            <select
              className="syslogs__select"
              value={level}
              onChange={e => setLevel(e.target.value)}
            >
              {LEVELS.map(l => (
                <option key={l} value={l}>{l || '全部'}</option>
              ))}
            </select>
          </label>
          <button
            className={`syslogs__toggle ${follow ? 'is-active' : ''}`}
            onClick={() => setFollow(f => !f)}
            disabled={!!date}
            title={date ? '选择历史日期时无法实时跟随' : '实时跟随新日志'}
          >
            <span className={`syslogs__live-dot ${isLive ? 'is-on' : ''}`} />
            {isLive ? '实时跟随中' : '实时跟随'}
          </button>
          <button className="syslogs__refresh" onClick={loadFiles} title="刷新文件列表">
            <span className="syslogs__refresh-icon">{Icons.refresh}</span>
          </button>
        </div>
      </header>

      <div className="syslogs__body">
        {/* ── Left: file list ── */}
        <aside className="syslogs__sidebar">
          <div className="syslogs__sidebar-title">日志文件</div>
          {files.length === 0 && !error && (
            <div className="syslogs__sidebar-empty">暂无日志文件</div>
          )}
          {files.map(f => (
            <button
              key={f.name}
              className={`syslogs__file ${selectedFile === f.name ? 'is-active' : ''}`}
              onClick={() => setSelectedFile(f.name)}
            >
              <span className="syslogs__file-name">{f.name}</span>
              <span className="syslogs__file-meta">
                <span>{f.size_human}</span>
                <span>{f.mtime ? new Date(f.mtime).toLocaleString('zh-CN', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}) : ''}</span>
              </span>
            </button>
          ))}
        </aside>

        {/* ── Right: log viewer ── */}
        <section className="syslogs__viewer">
          <div className="syslogs__viewer-bar">
            <span className="syslogs__viewer-file">{selectedFile || '—'}</span>
            {meta && (
              <span className="syslogs__viewer-stats">
                {meta.shown} 行{meta.truncated ? ` · 截断(共 ${meta.matched})` : ''}
                {!date && ` · 文件 ${meta.total}`}
              </span>
            )}
            {!autoScroll && (
              <button
                className="syslogs__resume"
                onClick={() => { setAutoScroll(true); }}
              >回到底部</button>
            )}
          </div>
          {error && <div className="syslogs__error">{error}</div>}
          {loading && lines.length === 0 ? (
            <div className="syslogs__loading">加载中…</div>
          ) : lines.length === 0 && !error ? (
            <div className="syslogs__empty">无匹配日志</div>
          ) : (
            <div className="syslogs__scroll" ref={scrollRef} onScroll={onScroll}>
              {(() => {
                // 仅渲染最近 RENDER_WINDOW 行，避免海量日志时 DOM 节点爆炸。
                // 行号仍按完整缓冲区计算（偏移 = 总行数 - 渲染数）。
                const total = lines.length;
                const start = Math.max(0, total - RENDER_WINDOW);
                const view = lines.slice(start);
                const baseNo = total - view.length;
                return view.map((line, i) => (
                  <div key={baseNo + i} className={`syslogs__line syslogs__line--${lineLevel(line)}`}>
                    <span className="syslogs__line-no">{baseNo + i + 1}</span>
                    <span className="syslogs__line-text">{line}</span>
                  </div>
                ));
              })()}
            </div>
          )}
        </section>
      </div>
    </div>
  );
};
