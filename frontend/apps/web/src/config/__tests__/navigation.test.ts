import {describe, expect, it} from 'vitest';
import {navGroups, scenarios, workflowStages, CALIBRATION_NOTES} from '../navigation';

const allItems = navGroups.flatMap((g) => g.items);
const allPaths = allItems.map((i) => i.path);

describe('navigation 配置完整性', () => {
  it('菜单项 path 唯一且 desc/label/icon 非空', () => {
    expect(new Set(allPaths).size).toBe(allPaths.length);
    for (const item of allItems) {
      expect(item.label.length).toBeGreaterThan(0);
      expect(item.desc.length).toBeGreaterThan(0);
      expect(item.desc.length).toBeLessThanOrEqual(16);
      expect(item.icon.length).toBeGreaterThan(0);
    }
  });

  it('菜单项图标全唯一(侧栏折叠态只显示图标,重复无法区分)', () => {
    const icons = allItems.map((i) => i.icon);
    expect(new Set(icons).size).toBe(icons.length);
  });

  it('分组 id 唯一,至少两组默认展开', () => {
    const ids = navGroups.map((g) => g.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(navGroups.filter((g) => g.defaultOpen).length).toBeGreaterThanOrEqual(2);
  });

  it('菜单规模护栏:7 组 26 项,各组数量固定(增删须显式改此断言)', () => {
    expect(navGroups.length).toBe(7);
    expect(navGroups.map((g) => g.items.length)).toEqual([2, 4, 6, 2, 5, 5, 2]);
    expect(allItems.length).toBe(26);
  });

  it('幽灵入口已转正:/checklist 在菜单中', () => {
    expect(allPaths).toContain('/checklist');
    expect(allPaths).toContain('/start');
  });

  it('场景卡:primary 与 links 均指向菜单内路径', () => {
    expect(scenarios.length).toBe(7);
    for (const s of scenarios) {
      expect(allPaths).toContain(s.primary);
      for (const link of s.links) {
        expect(allPaths).toContain(link.path);
      }
    }
  });

  it('工作流六层:标题/职责非空,链接均指向菜单内路径', () => {
    expect(workflowStages.map((s) => s.id)).toEqual(
      ['market', 'research', 'decide', 'hold', 'sell', 'review']);
    for (const stage of workflowStages) {
      expect(stage.title.length).toBeGreaterThan(0);
      expect(stage.role.length).toBeGreaterThan(0);
      expect(stage.links.length).toBeGreaterThan(0);
      for (const link of stage.links) {
        expect(allPaths).toContain(link.path);
      }
    }
  });

  it('口径速记非空', () => {
    expect(CALIBRATION_NOTES.length).toBeGreaterThanOrEqual(4);
    for (const note of CALIBRATION_NOTES) {
      expect(note.length).toBeGreaterThan(5);
    }
  });
});

import {getFlowContext} from '../navigation';

describe('工作流元数据', () => {
  it('每个 stage 都是合法环节或 start/system', () => {
    const validStages = ['start', 'market', 'research', 'decide', 'hold', 'review', 'system'];
    for (const item of allItems) {
      if (item.stage) expect(validStages).toContain(item.stage);
    }
  });

  it('prev/next 引用的 path 必须存在于菜单', () => {
    for (const item of allItems) {
      if (item.prev) expect(allPaths).toContain(item.prev);
      if (item.next) expect(allPaths).toContain(item.next);
    }
  });

  it('getFlowContext 解析主链页面', () => {
    const fin = getFlowContext('/financial');
    expect(fin?.stageTitle).toBe('研究');
    expect(fin?.prev?.path).toBe('/screener');
    expect(fin?.next?.path).toBe('/checklist');
  });

  it('getFlowContext 未知路径返回 null', () => {
    expect(getFlowContext('/nope')).toBeNull();
  });
});
