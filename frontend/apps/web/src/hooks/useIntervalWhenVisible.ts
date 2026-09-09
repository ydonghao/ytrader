/**
 * 可见性感知轮询：页面隐藏（切 Tab / 最小化）时暂停请求，
 * 恢复可见的瞬间立即补一次，避免回来先看一轮陈旧数据。
 *
 * fn 通过 ref 透传：fn 身份变化（如依赖 items 的回调）不会重建定时器。
 */
import { useEffect, useRef } from 'react';

export function useIntervalWhenVisible(fn: () => void, ms: number | null): void {
  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    if (ms == null) return;
    const tick = () => {
      if (!document.hidden) fnRef.current();
    };
    const onVisible = () => {
      if (!document.hidden) fnRef.current();
    };
    const id = setInterval(tick, ms);
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      clearInterval(id);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [ms]);
}
