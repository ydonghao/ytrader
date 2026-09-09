/**
 * 看板 store — 后端为唯一数据源(不本地持久化布局);
 * 活跃看板 id 存 localStorage 仅作便捷恢复。
 * 布局变更后 800ms 防抖 PUT 自动保存;切换看板/卸载前 flush。
 */
import {create} from 'zustand';
import {getApiBase} from '../../lib/api';
import {
  BoardCard,
  BoardLayout,
  EMPTY_LAYOUT,
  TimeRangeState,
  normalizeLayout,
} from './boardTypes';

const API_BASE = getApiBase();
const ACTIVE_KEY = 'ytrader_board_active';
const SAVE_DEBOUNCE_MS = 800;

export interface BoardSummary {
  id: number;
  name: string;
  sort_index: number;
  updated_at: string;
}

export type SaveState = 'idle' | 'saving' | 'saved' | 'error';

interface BoardsStore {
  boards: BoardSummary[];
  activeId: number | null;
  layout: BoardLayout;
  loading: boolean;
  loadError: string | null;
  saveState: SaveState;

  loadBoards: () => Promise<void>;
  selectBoard: (id: number) => Promise<void>;
  createBoard: (name: string) => Promise<boolean>;
  renameBoard: (name: string) => Promise<boolean>;
  deleteBoard: () => Promise<void>;
  retrySave: () => Promise<void>;
  flushSave: () => Promise<void>;

  setTimeRange: (tr: TimeRangeState) => void;
  addCard: (card: BoardCard) => void;
  updateCard: (id: string, patch: Partial<BoardCard>) => void;
  removeCard: (id: string) => void;
  bringToFront: (id: string) => void;
  sendToBack: (id: string) => void;
}

async function apiJson(url: string, init?: RequestInit): Promise<any> {
  const res = await fetch(url, init);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

function putLayout(activeId: number, layout: BoardLayout) {
  return apiJson(`${API_BASE}/board/boards/${activeId}`, {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({layout}),
  });
}

let saveTimer: number | null = null;

export const useBoards = create<BoardsStore>()((set, get) => {
  const scheduleSave = () => {
    if (!get().activeId) return;
    if (saveTimer !== null) window.clearTimeout(saveTimer);
    set({saveState: 'saving'});
    saveTimer = window.setTimeout(() => {
      saveTimer = null;
      void get().flushSave();
    }, SAVE_DEBOUNCE_MS);
  };

  /** 立即保存(有挂起定时器时取消定时改为立即) */
  const persistNow = async () => {
    const {activeId, layout} = get();
    if (!activeId) return;
    if (saveTimer !== null) {
      window.clearTimeout(saveTimer);
      saveTimer = null;
    }
    try {
      const json = await putLayout(activeId, layout);
      // 仅当无更新的变更挂起时才降级状态;否则保持 saving 由新定时器重试
      if (saveTimer === null) {
        set({saveState: json.code === 0 ? 'saved' : 'error'});
      }
    } catch {
      if (saveTimer === null) {
        set({saveState: 'error'});
      }
    }
  };

  const mutateLayout = (fn: (l: BoardLayout) => BoardLayout) => {
    set({layout: fn(get().layout)});
    scheduleSave();
  };

  return {
    boards: [],
    activeId: null,
    layout: EMPTY_LAYOUT,
    loading: false,
    loadError: null,
    saveState: 'idle',

    loadBoards: async () => {
      set({loading: true, loadError: null});
      try {
        const json = await apiJson(`${API_BASE}/board/boards`);
        if (json.code !== 0) throw new Error(json.msg || '加载看板列表失败');
        const boards: BoardSummary[] = json.data || [];
        set({boards, loading: false});
        const saved = Number(localStorage.getItem(ACTIVE_KEY));
        const target = boards.find((b) => b.id === saved) || boards[0];
        if (target) await get().selectBoard(target.id);
      } catch (e) {
        set({loading: false, loadError: String(e)});
      }
    },

    selectBoard: async (id) => {
      if (get().activeId === id) return;
      // 切走前把未落盘的布局刷出去(挂起定时器或请求在途都算未保存)
      if (saveTimer !== null || get().saveState === 'saving') await persistNow();
      set({loadError: null});
      try {
        const json = await apiJson(`${API_BASE}/board/boards/${id}`);
        if (json.code !== 0) throw new Error(json.msg || '加载看板失败');
        // 取数期间用户又动了旧板:先把旧板最新布局刷出去,再切换
        if (saveTimer !== null) await persistNow();
        localStorage.setItem(ACTIVE_KEY, String(id));
        set({
          activeId: id,
          layout: normalizeLayout(json.data?.layout),
          saveState: 'idle',
        });
      } catch (e) {
        set({loadError: String(e)});
      }
    },

    createBoard: async (name) => {
      try {
        const json = await apiJson(`${API_BASE}/board/boards`, {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({name}),
        });
        if (json.code !== 0) throw new Error(json.msg || '新建失败');
        const b: BoardSummary = {
          id: json.data.id,
          name: json.data.name,
          sort_index: json.data.sort_index,
          updated_at: json.data.updated_at,
        };
        set({boards: [...get().boards, b]});
        await get().selectBoard(b.id);
        return true;
      } catch {
        return false;
      }
    },

    renameBoard: async (name) => {
      const {activeId, boards} = get();
      if (!activeId || !name.trim()) return false;
      try {
        const json = await apiJson(`${API_BASE}/board/boards/${activeId}`, {
          method: 'PUT',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({name: name.trim()}),
        });
        if (json.code !== 0) throw new Error(json.msg || '重命名失败');
        set({
          boards: boards.map((b) =>
            b.id === activeId ? {...b, name: name.trim()} : b,
          ),
        });
        return true;
      } catch {
        return false;
      }
    },

    deleteBoard: async () => {
      const {activeId, boards} = get();
      if (!activeId) return;
      if (saveTimer !== null || get().saveState === 'saving') await persistNow();
      try {
        const json = await apiJson(
          `${API_BASE}/board/boards/${activeId}`,
          {method: 'DELETE'},
        );
        if (json.code !== 0) throw new Error(json.msg || '删除失败');
      } catch (e) {
        // 服务端失败时保持本地状态不变,经 loadError 透出(Task 5 顶栏已有展示位)
        set({loadError: e instanceof Error ? e.message : String(e)});
        return;
      }
      const rest = boards.filter((b) => b.id !== activeId);
      set({boards: rest, activeId: null, layout: EMPTY_LAYOUT, saveState: 'idle'});
      localStorage.removeItem(ACTIVE_KEY);
      if (rest.length > 0) await get().selectBoard(rest[0].id);
    },

    retrySave: async () => {
      await persistNow();
    },

    flushSave: async () => {
      if (saveTimer !== null || get().saveState === 'saving') {
        await persistNow();
      }
    },

    setTimeRange: (tr) =>
      mutateLayout((l) => ({...l, timeRange: tr})),

    addCard: (card) =>
      mutateLayout((l) => ({
        ...l,
        maxZ: Math.max(l.maxZ, card.z),
        cards: [...l.cards, card],
      })),

    updateCard: (id, patch) =>
      mutateLayout((l) => ({
        ...l,
        cards: l.cards.map((c) => (c.id === id ? {...c, ...patch} : c)),
      })),

    removeCard: (id) =>
      mutateLayout((l) => ({...l, cards: l.cards.filter((c) => c.id !== id)})),

    bringToFront: (id) =>
      mutateLayout((l) => ({
        ...l,
        maxZ: l.maxZ + 1,
        cards: l.cards.map((c) => (c.id === id ? {...c, z: l.maxZ + 1} : c)),
      })),

    sendToBack: (id) =>
      mutateLayout((l) => {
        const minZ = l.cards.reduce((m, c) => Math.min(m, c.z), 0);
        return {
          ...l,
          cards: l.cards.map((c) => (c.id === id ? {...c, z: minZ - 1} : c)),
        };
      }),
  };
});
