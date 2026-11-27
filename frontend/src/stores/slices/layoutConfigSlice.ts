import { restClient } from '../../api/restClient';
import {
  DEFAULT_LAYOUT_CONFIG,
  normalizeLayoutConfig,
  normalizeWritingRegion,
  type CustomUserPreset,
  type LayoutConfig,
  type PageRuleOverride,
  type PageRulesConfig,
} from '../../api/types';
import { useViewportStore } from '../useViewportStore';
import {
  enforceUniformSSOT,
  scheduleCompose,
  type DocLayoutSliceCreator,
  type LayoutConfigSlice,
} from './storeTypes';

const CUSTOM_PRESETS_KEY = 'handwrite_custom_presets_v1';

function loadCustomPresets(): CustomUserPreset[] {
  try {
    const raw = window.localStorage.getItem(CUSTOM_PRESETS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((x) => x && typeof x.preset_id === 'string' && typeof x.name === 'string')
      .map((x) => ({
        preset_id: x.preset_id,
        name: x.name,
        description: typeof x.description === 'string' ? x.description : '',
        created_at: typeof x.created_at === 'string' ? x.created_at : '',
        config: enforceUniformSSOT(normalizeLayoutConfig(x.config)),
      }));
  } catch {
    return [];
  }
}

function saveCustomPresetsToStorage(items: CustomUserPreset[]): void {
  try {
    window.localStorage.setItem(CUSTOM_PRESETS_KEY, JSON.stringify(items));
  } catch {
    // ignore storage quota errors
  }
}

function matchPaperPreset(widthMm: number, heightMm: number): {
  size: 'A4' | 'A5' | 'B5' | 'Letter' | 'custom';
  orientation: 'portrait' | 'landscape';
} {
  const presets: Array<{ size: 'A4' | 'A5' | 'B5' | 'Letter'; w: number; h: number }> = [
    { size: 'A4', w: 210, h: 297 },
    { size: 'A5', w: 148, h: 210 },
    { size: 'B5', w: 176, h: 250 },
    { size: 'Letter', w: 215.9, h: 279.4 },
  ];
  for (const p of presets) {
    if (Math.abs(widthMm - p.w) <= 1.2 && Math.abs(heightMm - p.h) <= 1.2) {
      return { size: p.size, orientation: 'portrait' };
    }
    if (Math.abs(widthMm - p.h) <= 1.2 && Math.abs(heightMm - p.w) <= 1.2) {
      return { size: p.size, orientation: 'landscape' };
    }
  }
  return { size: 'custom', orientation: widthMm > heightMm ? 'landscape' : 'portrait' };
}

function promoteUniformOverridesToGlobal(cfg: LayoutConfig): LayoutConfig {
  if (cfg.page_rules.strategy !== 'uniform') return cfg;
  const u = cfg.page_rules.uniform;
  const next: LayoutConfig = {
    ...cfg,
    page: {
      ...cfg.page,
      margins_mm: u.margins_mm ? { ...u.margins_mm } : cfg.page.margins_mm,
    },
    text: {
      ...cfg.text,
      font_size_mm: u.font_size_mm ?? cfg.text.font_size_mm,
      line_spacing: u.line_spacing ?? cfg.text.line_spacing,
      line_spacing_mm: u.line_spacing_mm !== null ? u.line_spacing_mm : cfg.text.line_spacing_mm,
      paragraph_spacing_mm: u.paragraph_spacing_mm ?? cfg.text.paragraph_spacing_mm,
      ruled: u.ruled ? { ...u.ruled } : cfg.text.ruled,
    },
  };
  return enforceUniformSSOT(next);
}

export const createLayoutConfigSlice: DocLayoutSliceCreator<LayoutConfigSlice> = (set, get) => ({
  config: enforceUniformSSOT(normalizeLayoutConfig(DEFAULT_LAYOUT_CONFIG)),
  presets: [],
  customPresets: loadCustomPresets(),
  backgrounds: [],
  uploadingBackground: false,

  fetchPresets: async () => {
    try {
      const res = await restClient.listLayoutPresets();
      const normalized = (res.presets || []).map((p) => ({
        ...p,
        config: promoteUniformOverridesToGlobal(normalizeLayoutConfig(p.config)),
      }));
      set({ presets: normalized });
    } catch {
      // keep existing
    }
  },

  fetchBackgrounds: async () => {
    try {
      const res = await restClient.listBackgrounds();
      set({ backgrounds: res.backgrounds || [] });
    } catch {
      // keep existing
    }
  },

  uploadBackground: async (file, opts) => {
    set({ uploadingBackground: true });
    try {
      const cfg = get().config;
      const margins = opts?.margins ?? cfg.page.margins_mm;
      const res = await restClient.uploadBackground({
        file,
        name: opts?.name ?? '',
        width_mm: opts?.width_mm ?? cfg.page.width_mm,
        height_mm: opts?.height_mm ?? cfg.page.height_mm,
        margin_top: margins.top,
        margin_right: margins.right,
        margin_bottom: margins.bottom,
        margin_left: margins.left,
      });
      await get().fetchBackgrounds();
      useViewportStore
        .getState()
        .pushToast(`已上传背景底稿：${res.background.name}`, 'success');
      return res.background;
    } catch (err) {
      useViewportStore
        .getState()
        .pushToast(`上传底稿失败: ${err instanceof Error ? err.message : String(err)}`, 'error');
      return null;
    } finally {
      set({ uploadingBackground: false });
    }
  },

  deleteBackground: async (backgroundId) => {
    try {
      await restClient.deleteBackground(backgroundId);
      const cfg = get().config;
      const cleanRule = (r: PageRuleOverride) =>
        r.background_id === backgroundId ? { ...r, background_id: null } : r;
      const nextCustom: PageRulesConfig['custom_pages'] = {};
      for (const [k, v] of Object.entries(cfg.page_rules.custom_pages)) {
        nextCustom[k] = cleanRule(v);
      }
      set({
        config: {
          ...cfg,
          page_rules: {
            ...cfg.page_rules,
            uniform: cleanRule(cfg.page_rules.uniform),
            first_page: cleanRule(cfg.page_rules.first_page),
            rest_pages: cleanRule(cfg.page_rules.rest_pages),
            odd_pages: cleanRule(cfg.page_rules.odd_pages),
            even_pages: cleanRule(cfg.page_rules.even_pages),
            custom_pages: nextCustom,
          },
        },
      });
      await get().fetchBackgrounds();
      void get().composeNow();
      useViewportStore.getState().pushToast('已删除自定义背景底稿', 'info');
    } catch (err) {
      useViewportStore
        .getState()
        .pushToast(`删除底稿失败: ${err instanceof Error ? err.message : String(err)}`, 'error');
    }
  },

  applyPreset: (presetConfig, presetLabel) => {
    const normalized = promoteUniformOverridesToGlobal(normalizeLayoutConfig(presetConfig));
    const vp = useViewportStore.getState();
    const pr = normalized.page_rules;
    const hasBg =
      Boolean(pr.uniform.background_id) ||
      Boolean(pr.first_page.background_id) ||
      Boolean(pr.rest_pages.background_id) ||
      Boolean(pr.odd_pages.background_id) ||
      Boolean(pr.even_pages.background_id) ||
      Object.values(pr.custom_pages).some((r) => Boolean(r.background_id));

    if (hasBg || normalized.mode === 'overlay') {
      vp.setShowUnderlay(true);
    }
    if (normalized.mode === 'reflow') {
      vp.setSelectedBlockId(null);
    }
    get().updateConfig(() => normalized, true);
    if (presetLabel) {
      vp.pushToast(`已套用预设：${presetLabel}`, 'success');
    }
  },

  saveCustomPreset: (name, description = '') => {
    const trimmed = name.trim();
    if (!trimmed) return;
    const presetId = `custom_${Date.now().toString(36)}`;
    const snapshot = enforceUniformSSOT(
      normalizeLayoutConfig({
        ...structuredClone(get().config),
        preset_id: presetId,
      }),
    );
    const entry: CustomUserPreset = {
      preset_id: presetId,
      name: trimmed,
      description:
        description.trim() ||
        `${snapshot.page.size} · ${snapshot.text.font_size_mm.toFixed(1)}mm · ${
          snapshot.page_rules.strategy === 'first_and_rest'
            ? '首页 A / 续页 B'
            : snapshot.page_rules.strategy === 'odd_even'
              ? '奇偶交替'
              : snapshot.page_rules.strategy === 'custom'
                ? '自由逐页'
                : '统一排版'
        }`,
      created_at: new Date().toISOString(),
      config: snapshot,
    };
    const next = [entry, ...get().customPresets];
    saveCustomPresetsToStorage(next);
    set({
      customPresets: next,
      config: { ...get().config, preset_id: presetId },
    });
    useViewportStore.getState().pushToast(`已保存自定义预设：${trimmed}`, 'success');
  },

  deleteCustomPreset: (presetId) => {
    const next = get().customPresets.filter((p) => p.preset_id !== presetId);
    saveCustomPresetsToStorage(next);
    set({ customPresets: next });
    useViewportStore.getState().pushToast('已移除自定义预设', 'info');
  },

  updateConfig: (updater, immediate = false) => {
    set((s) => ({
      config: enforceUniformSSOT(updater(s.config)),
    }));
    scheduleCompose(get().composeNow, immediate);
  },

  updatePageRules: (updater, immediate = true) => {
    set((s) => ({
      config: enforceUniformSSOT({
        ...s.config,
        preset_id: null,
        page_rules: updater(s.config.page_rules),
      }),
    }));
    scheduleCompose(get().composeNow, immediate);
  },

  assignBackgroundToSlot: (bg, slot) => {
    useViewportStore.getState().setShowUnderlay(true);
    set((s) => {
      const prevPr = s.config.page_rules;
      let nextCfg: LayoutConfig = {
        ...s.config,
        preset_id: null,
      };

      if (slot === 'uniform') {
        const paper = matchPaperPreset(bg.width_mm, bg.height_mm);
        nextCfg = {
          ...nextCfg,
          page: {
            ...nextCfg.page,
            size: paper.size,
            orientation: paper.orientation,
            width_mm: bg.width_mm,
            height_mm: bg.height_mm,
            margins_mm: { ...bg.recommended_margins_mm },
            underlay_fit: 'fill',
            underlay_width_mm: null,
            underlay_height_mm: null,
            underlay_offset_x_mm: 0,
            underlay_offset_y_mm: 0,
          },
          text: {
            ...nextCfg.text,
            ruled: bg.recommended_ruled_pitch_mm
              ? {
                  style: bg.background_id.includes('grid') ? 'grid' : 'lines',
                  pitch_mm: bg.recommended_ruled_pitch_mm,
                  draw: false,
                }
              : nextCfg.text.ruled,
          },
          page_rules: {
            ...prevPr,
            strategy: 'uniform',
            uniform: {
              ...prevPr.uniform,
              background_id: bg.background_id,
              margins_mm: null,
              font_size_mm: null,
              line_spacing: null,
              line_spacing_mm: null,
              paragraph_spacing_mm: null,
              ruled: null,
            },
          },
        };
        return { config: nextCfg };
      }

      const applyToRule = (r: PageRuleOverride): PageRuleOverride => ({
        ...r,
        background_id: bg.background_id,
        margins_mm: { ...bg.recommended_margins_mm },
        ruled: bg.recommended_ruled_pitch_mm
          ? {
              style: bg.background_id.includes('grid') ? 'grid' : 'lines',
              pitch_mm: bg.recommended_ruled_pitch_mm,
              draw: false,
            }
          : r.ruled,
      });

      const nextPr =
        prevPr.strategy === 'odd_even'
          ? slot === 'a'
            ? { ...prevPr, odd_pages: applyToRule(prevPr.odd_pages) }
            : { ...prevPr, even_pages: applyToRule(prevPr.even_pages) }
          : slot === 'a'
            ? { ...prevPr, strategy: 'first_and_rest' as const, first_page: applyToRule(prevPr.first_page) }
            : { ...prevPr, strategy: 'first_and_rest' as const, rest_pages: applyToRule(prevPr.rest_pages) };

      return {
        config: {
          ...nextCfg,
          page_rules: nextPr,
        },
      };
    });
    void get().composeNow();
  },

  clearPageRuleOverrides: (pageIndex) => {
    get().updatePageRules((pr) => {
      const clear = (r: PageRuleOverride): PageRuleOverride => ({
        ...r,
        margins_mm: null,
        font_size_mm: null,
        line_spacing: null,
        line_spacing_mm: null,
        paragraph_spacing_mm: null,
        ruled: null,
      });
      if (pr.strategy === 'uniform') return { ...pr, uniform: clear(pr.uniform) };
      if (pr.strategy === 'first_and_rest') {
        return pageIndex === 0
          ? { ...pr, first_page: clear(pr.first_page) }
          : { ...pr, rest_pages: clear(pr.rest_pages) };
      }
      if (pr.strategy === 'odd_even') {
        return pageIndex % 2 === 0
          ? { ...pr, odd_pages: clear(pr.odd_pages) }
          : { ...pr, even_pages: clear(pr.even_pages) };
      }
      const pNo = String(pageIndex + 1);
      if (pr.custom_pages[pNo]) {
        return {
          ...pr,
          custom_pages: { ...pr.custom_pages, [pNo]: clear(pr.custom_pages[pNo]) },
        };
      }
      return pr;
    }, true);
    useViewportStore.getState().pushToast('已清除当前页局部覆盖，恢复跟随全局设置', 'info');
  },

  addRegion: (partial) => {
    const existing = get().config.regions;
    const region = normalizeWritingRegion(
      {
        region_id: `reg_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`,
        order: existing.length,
        page_scope: String(get().currentPageIndex + 1),
        ...partial,
      },
      existing.length,
    );
    const shouldCompose = region.role === 'body' || region.text.trim().length > 0;
    set((s) => ({
      config: {
        ...s.config,
        preset_id: null,
        regions: [...s.config.regions, region],
      },
    }));
    const vp = useViewportStore.getState();
    vp.setShowRegions(true);
    vp.setSelectedRegionId(region.region_id);
    if (shouldCompose) {
      void get().composeNow();
    }
    return region;
  },

  updateRegion: (regionId, patch, immediate = false) => {
    get().updateConfig(
      (prev) => ({
        ...prev,
        preset_id: null,
        regions: prev.regions.map((r) => (r.region_id === regionId ? { ...r, ...patch } : r)),
      }),
      immediate,
    );
  },

  removeRegion: (regionId) => {
    const vp = useViewportStore.getState();
    if (vp.selectedRegionId === regionId) {
      vp.setSelectedRegionId(null);
    }
    get().updateConfig(
      (prev) => ({
        ...prev,
        preset_id: null,
        regions: prev.regions.filter((r) => r.region_id !== regionId),
      }),
      true,
    );
  },

  duplicateRegion: (regionId) => {
    const src = get().config.regions.find((r) => r.region_id === regionId);
    if (!src) return;
    get().addRegion({
      ...structuredClone(src),
      region_id: undefined,
      name: `${src.name} 副本`,
      x_mm: Math.min(get().config.page.width_mm - src.width_mm, Number((src.x_mm + 6).toFixed(1))),
      y_mm: Math.min(get().config.page.height_mm - src.height_mm, Number((src.y_mm + 6).toFixed(1))),
      order: get().config.regions.length,
    });
  },

  clearRegions: () => {
    useViewportStore.getState().setSelectedRegionId(null);
    get().updateConfig(
      (prev) => ({
        ...prev,
        preset_id: null,
        regions: [],
      }),
      true,
    );
  },

  resetToBlankA4: () => {
    const builtinBgIds = new Set(
      get()
        .backgrounds.filter((b) => b.kind === 'builtin')
        .map((b) => b.background_id),
    );
    const cleanRule = (r: PageRuleOverride) =>
      r.background_id && builtinBgIds.has(r.background_id) ? { ...r, background_id: null } : r;
    get().updateConfig((prev) => {
      const nextCustom: PageRulesConfig['custom_pages'] = {};
      for (const [k, v] of Object.entries(prev.page_rules.custom_pages)) {
        nextCustom[k] = cleanRule(v);
      }
      return {
        ...prev,
        preset_id: null,
        page: {
          ...prev.page,
          size: 'A4',
          width_mm: 210,
          height_mm: 297,
          orientation: 'portrait',
          underlay_fit: 'fill',
          underlay_width_mm: null,
          underlay_height_mm: null,
          underlay_offset_x_mm: 0,
          underlay_offset_y_mm: 0,
        },
        page_rules: {
          ...prev.page_rules,
          uniform: { ...cleanRule(prev.page_rules.uniform), background_id: null },
          first_page: cleanRule(prev.page_rules.first_page),
          rest_pages: cleanRule(prev.page_rules.rest_pages),
          odd_pages: cleanRule(prev.page_rules.odd_pages),
          even_pages: cleanRule(prev.page_rules.even_pages),
          custom_pages: nextCustom,
        },
      };
    }, true);
  },

  setMode: (mode) => {
    const vp = useViewportStore.getState();
    if (mode === 'overlay') {
      vp.setShowUnderlay(true);
    } else {
      vp.setSelectedBlockId(null);
    }
    get().updateConfig((prev) => ({ ...prev, mode }), true);
  },

  toggleOverlayBlock: (blockId, enabled) => {
    get().updateConfig(
      (prev) => {
        const cur = prev.overlay.blocks[blockId] ?? { enabled: true, nudge_mm: { x: 0, y: 0 } };
        return {
          ...prev,
          overlay: {
            ...prev.overlay,
            blocks: {
              ...prev.overlay.blocks,
              [blockId]: { ...cur, enabled },
            },
          },
        };
      },
      true,
    );
  },

  nudgeOverlayBlock: (blockId, dx, dy) => {
    get().updateConfig((prev) => {
      const cur = prev.overlay.blocks[blockId] ?? { enabled: true, nudge_mm: { x: 0, y: 0 } };
      return {
        ...prev,
        overlay: {
          ...prev.overlay,
          blocks: {
            ...prev.overlay.blocks,
            [blockId]: {
              ...cur,
              nudge_mm: {
                x: Number((cur.nudge_mm.x + dx).toFixed(2)),
                y: Number((cur.nudge_mm.y + dy).toFixed(2)),
              },
            },
          },
        },
      };
    });
  },

  setOverlayBlockNudge: (blockId, x, y) => {
    get().updateConfig((prev) => {
      const cur = prev.overlay.blocks[blockId] ?? { enabled: true, nudge_mm: { x: 0, y: 0 } };
      return {
        ...prev,
        overlay: {
          ...prev.overlay,
          blocks: {
            ...prev.overlay.blocks,
            [blockId]: {
              ...cur,
              nudge_mm: { x: Number(x.toFixed(2)), y: Number(y.toFixed(2)) },
            },
          },
        },
      };
    });
  },

  resetOverlayTransform: () => {
    get().updateConfig(
      (prev) => ({
        ...prev,
        overlay: {
          offset_mm: { x: 0, y: 0 },
          scale: 1.0,
          rotation_deg: 0,
          underlay_opacity: 0.42,
          blocks: {},
        },
      }),
      true,
    );
  },
});
