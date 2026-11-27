// Default layout configuration, normalizers, and page rule helpers.

import type {
  LayoutConfig,
  PageRuleOverride,
  PageRulesConfig,
  TableBorderStyle,
  WritingRegion,
} from './layout';

export const TABLE_STYLE_OPTIONS: Array<{
  value: TableBorderStyle;
  label: string;
  desc: string;
}> = [
  { value: 'grid', label: '标准网格', desc: '完整内外边框与均匀留白' },
  { value: 'compact', label: '紧凑窄小', desc: '窄幅 78%、紧缩内边距与紧凑行高' },
  { value: 'three_line', label: '学术三线', desc: '双顶底线 + 表头横线，无竖线' },
  { value: 'horizontal', label: '仅横线', desc: '保留水平分割线，去掉竖框线' },
  { value: 'dashed', label: '虚线轻框', desc: '手绘断续短虚线轻量化边框' },
  { value: 'minimal', label: '极简外框', desc: '仅外边框 + 表头线' },
  { value: 'none', label: '无框线', desc: '纯对齐文本列，不绘制线条' },
];

export function applyTableStylePreset(
  prev: LayoutConfig['table'],
  style: TableBorderStyle,
): LayoutConfig['table'] {
  if (style === 'compact') {
    return {
      ...prev,
      draw_borders: true,
      border_style: 'compact',
      width_ratio: 0.78,
      cell_padding_mm: 0.65,
      row_height_scale: 0.76,
      font_scale: 0.76,
    };
  }
  if (style === 'none') {
    return {
      ...prev,
      draw_borders: false,
      border_style: 'none',
    };
  }
  if (style === 'grid') {
    return {
      ...prev,
      draw_borders: true,
      border_style: 'grid',
      width_ratio: 1.0,
      cell_padding_mm: 1.4,
      row_height_scale: 1.0,
      font_scale: 0.86,
    };
  }
  return {
    ...prev,
    draw_borders: true,
    border_style: style,
  };
}

export function createDefaultPageRuleOverride(label = ''): PageRuleOverride {
  return {
    label,
    background_id: null,
    background_opacity: 0.72,
    writer_id: null,
    margins_mm: null,
    font_size_mm: null,
    line_spacing: null,
    line_spacing_mm: null,
    paragraph_spacing_mm: null,
    ruled: null,
  };
}

export function createDefaultPageRules(): PageRulesConfig {
  return {
    strategy: 'uniform',
    uniform: createDefaultPageRuleOverride('统一底稿'),
    first_page: createDefaultPageRuleOverride('首页方案 A'),
    rest_pages: createDefaultPageRuleOverride('后续页方案 B'),
    odd_pages: createDefaultPageRuleOverride('奇数页方案 A'),
    even_pages: createDefaultPageRuleOverride('偶数页方案 B'),
    custom_pages: {},
  };
}

export const DEFAULT_LAYOUT_CONFIG: LayoutConfig = {
  preset_id: null,
  mode: 'reflow',
  page: {
    size: 'A4',
    width_mm: 210,
    height_mm: 297,
    orientation: 'portrait',
    margins_mm: { top: 22, right: 20, bottom: 22, left: 20 },
    underlay_fit: 'fill',
    underlay_width_mm: null,
    underlay_height_mm: null,
    underlay_offset_x_mm: 0,
    underlay_offset_y_mm: 0,
  },
  text: {
    font_size_mm: 6.0,
    char_scale_x: 1.0,
    char_scale_y: 1.0,
    line_spacing: 1.5,
    line_spacing_mm: null,
    char_spacing: 0.05,
    paragraph_spacing_mm: 3.0,
    first_line_indent_chars: 2.0,
    align: 'justify',
    ruled: { style: 'none', pitch_mm: 9.0, draw: false },
  },
  perturb: {
    seed: 42,
    neatness: 0.72,
    scale_jitter: 0.08,
    slant_deg: 2.5,
    baseline_wave_amp_mm: 0.45,
    baseline_wave_period_mm: 75.0,
    spacing_jitter: 0.08,
    rotation_jitter_deg: 1.2,
    variant_strategy: 'random_no_repeat',
    variant_no_repeat_window: 3,
  },
  formula: { scale: 0.95, line_spacing_mm: -0.8, inner_row_spacing: -0.04, stroke_style: 'handwrite' },
  chart: {
    image_render_mode: 'outline',
    contour_threshold: 185,
    hatch_spacing_mm: 1.8,
    hatch_angle_deg: 45,
    hatch_style: 'parallel',
    hand_jitter_mm: 0.25,
    keep_caption_with_figure: true,
  },
  table: {
    draw_borders: true,
    border_style: 'grid',
    width_ratio: 1.0,
    cell_padding_mm: 1.4,
    row_height_scale: 1.0,
    font_scale: 0.86,
    align: 'center',
    hand_jitter_mm: 0.2,
    keep_caption_with_table: true,
  },
  overlay: {
    offset_mm: { x: 0, y: 0 },
    scale: 1.0,
    rotation_deg: 0.0,
    underlay_opacity: 0.35,
    blocks: {},
  },
  optimize: { travel: 'greedy_2opt', simplify_tol_mm: 0.08, join_tol_mm: 0.15 },
  fallback: { policy: 'blank' },
  page_rules: createDefaultPageRules(),
  regions: [],
  writer_mix: [],
};

export function normalizeWritingRegion(
  raw: Partial<WritingRegion> | undefined,
  fallbackIndex: number,
): WritingRegion {
  return {
    region_id: raw?.region_id || `reg_${fallbackIndex + 1}`,
    name: raw?.name || `区域 #${fallbackIndex + 1}`,
    role: raw?.role === 'body' ? 'body' : 'field',
    field_key: raw?.field_key ?? '',
    text: raw?.text ?? '',
    page_scope: raw?.page_scope || '1',
    order: typeof raw?.order === 'number' ? raw.order : fallbackIndex,
    x_mm: typeof raw?.x_mm === 'number' ? raw.x_mm : 20,
    y_mm: typeof raw?.y_mm === 'number' ? raw.y_mm : 20,
    width_mm: typeof raw?.width_mm === 'number' ? Math.max(4, raw.width_mm) : 80,
    height_mm: typeof raw?.height_mm === 'number' ? Math.max(3, raw.height_mm) : 12,
    font_size_mm: typeof raw?.font_size_mm === 'number' ? raw.font_size_mm : null,
    line_spacing: typeof raw?.line_spacing === 'number' ? raw.line_spacing : null,
    line_spacing_mm: typeof raw?.line_spacing_mm === 'number' ? raw.line_spacing_mm : null,
    paragraph_spacing_mm: typeof raw?.paragraph_spacing_mm === 'number' ? raw.paragraph_spacing_mm : null,
    char_spacing: typeof raw?.char_spacing === 'number' ? raw.char_spacing : null,
    align: raw?.align ?? 'left',
    valign: raw?.valign ?? 'middle',
    single_line: raw?.single_line !== undefined ? Boolean(raw.single_line) : true,
    auto_fit: raw?.auto_fit !== undefined ? Boolean(raw.auto_fit) : true,
    writer_id: raw?.writer_id ?? null,
    neatness: typeof raw?.neatness === 'number' ? raw.neatness : null,
    enabled: raw?.enabled !== undefined ? Boolean(raw.enabled) : true,
  };
}

function normalizeRuleOverride(
  raw: Partial<PageRuleOverride> | undefined,
  fallbackLabel: string,
): PageRuleOverride {
  const base = createDefaultPageRuleOverride(fallbackLabel);
  if (!raw) return base;
  return {
    ...base,
    ...raw,
    label: raw.label ?? fallbackLabel,
    background_id: raw.background_id ?? null,
    background_opacity:
      typeof raw.background_opacity === 'number' ? raw.background_opacity : base.background_opacity,
    writer_id: raw.writer_id ?? null,
    margins_mm: raw.margins_mm ? { ...raw.margins_mm } : null,
    font_size_mm: typeof raw.font_size_mm === 'number' ? raw.font_size_mm : null,
    line_spacing: typeof raw.line_spacing === 'number' ? raw.line_spacing : null,
    line_spacing_mm: typeof raw.line_spacing_mm === 'number' ? raw.line_spacing_mm : null,
    paragraph_spacing_mm: typeof raw.paragraph_spacing_mm === 'number' ? raw.paragraph_spacing_mm : null,
    ruled: raw.ruled ? { ...raw.ruled } : null,
  };
}

export function normalizeLayoutConfig(raw?: Partial<LayoutConfig> | null): LayoutConfig {
  const base = structuredClone(DEFAULT_LAYOUT_CONFIG);
  if (!raw) return base;
  const pr = raw.page_rules;
  const customPages: Record<string, PageRuleOverride> = {};
  if (pr?.custom_pages) {
    for (const [k, v] of Object.entries(pr.custom_pages)) {
      customPages[k] = normalizeRuleOverride(v, v?.label || `规则 ${k}`);
    }
  }
  return {
    ...base,
    ...raw,
    preset_id: raw.preset_id ?? null,
    page: {
      ...base.page,
      ...raw.page,
      margins_mm: { ...base.page.margins_mm, ...raw.page?.margins_mm },
      underlay_fit:
        raw.page?.underlay_fit === 'contain' || raw.page?.underlay_fit === 'custom'
          ? raw.page.underlay_fit
          : raw.page?.underlay_width_mm != null || raw.page?.underlay_height_mm != null
            ? 'custom'
            : 'fill',
      underlay_width_mm:
        typeof raw.page?.underlay_width_mm === 'number' ? raw.page.underlay_width_mm : null,
      underlay_height_mm:
        typeof raw.page?.underlay_height_mm === 'number' ? raw.page.underlay_height_mm : null,
      underlay_offset_x_mm:
        typeof raw.page?.underlay_offset_x_mm === 'number' ? raw.page.underlay_offset_x_mm : 0,
      underlay_offset_y_mm:
        typeof raw.page?.underlay_offset_y_mm === 'number' ? raw.page.underlay_offset_y_mm : 0,
    },
    text: {
      ...base.text,
      ...raw.text,
      char_scale_x: typeof raw.text?.char_scale_x === 'number' ? raw.text.char_scale_x : 1.0,
      char_scale_y: typeof raw.text?.char_scale_y === 'number' ? raw.text.char_scale_y : 1.0,
      line_spacing_mm:
        typeof raw.text?.line_spacing_mm === 'number' ? raw.text.line_spacing_mm : null,
      ruled: { ...base.text.ruled, ...raw.text?.ruled },
    },
    perturb: { ...base.perturb, ...raw.perturb },
    formula: { ...base.formula, ...raw.formula },
    chart: {
      ...base.chart,
      ...raw.chart,
      image_render_mode: raw.chart?.image_render_mode ?? base.chart.image_render_mode,
      contour_threshold:
        typeof raw.chart?.contour_threshold === 'number'
          ? raw.chart.contour_threshold
          : base.chart.contour_threshold,
      keep_caption_with_figure:
        typeof raw.chart?.keep_caption_with_figure === 'boolean'
          ? raw.chart.keep_caption_with_figure
          : base.chart.keep_caption_with_figure,
    },
    table: {
      ...base.table,
      ...raw.table,
      border_style: raw.table?.border_style ?? (raw.table?.draw_borders === false ? 'none' : base.table.border_style),
      width_ratio: typeof raw.table?.width_ratio === 'number' ? raw.table.width_ratio : base.table.width_ratio,
      cell_padding_mm: typeof raw.table?.cell_padding_mm === 'number' ? raw.table.cell_padding_mm : base.table.cell_padding_mm,
      row_height_scale: typeof raw.table?.row_height_scale === 'number' ? raw.table.row_height_scale : base.table.row_height_scale,
      font_scale: typeof raw.table?.font_scale === 'number' ? raw.table.font_scale : base.table.font_scale,
      align: raw.table?.align ?? base.table.align,
      keep_caption_with_table:
        typeof raw.table?.keep_caption_with_table === 'boolean'
          ? raw.table.keep_caption_with_table
          : base.table.keep_caption_with_table,
    },
    overlay: {
      ...base.overlay,
      ...raw.overlay,
      offset_mm: { ...base.overlay.offset_mm, ...raw.overlay?.offset_mm },
      blocks: raw.overlay?.blocks ? structuredClone(raw.overlay.blocks) : {},
    },
    optimize: { ...base.optimize, ...raw.optimize },
    fallback: {
      policy: raw.fallback?.policy ?? base.fallback.policy,
    },
    page_rules: {
      strategy: pr?.strategy ?? 'uniform',
      uniform: normalizeRuleOverride(pr?.uniform, '统一底稿'),
      first_page: normalizeRuleOverride(pr?.first_page, '首页方案 A'),
      rest_pages: normalizeRuleOverride(pr?.rest_pages, '后续页方案 B'),
      odd_pages: normalizeRuleOverride(pr?.odd_pages, '奇数页方案 A'),
      even_pages: normalizeRuleOverride(pr?.even_pages, '偶数页方案 B'),
      custom_pages: customPages,
    },
    regions: Array.isArray(raw.regions)
      ? raw.regions.map((r, i) => normalizeWritingRegion(r, i))
      : [],
  };
}

/**
 * Check if 0-based `pageIndex` matches a WritingRegion `page_scope` string.
 */
export function matchesPageScope(scope: string | undefined, pageIndex: number): boolean {
  const raw = (scope || 'all').trim().toLowerCase();
  if (!raw || raw === 'all' || raw === '*' || raw === 'every') return true;
  const pageNo = pageIndex + 1;
  for (const part of raw.split(',')) {
    const t = part.trim();
    if (!t) continue;
    if (t === 'first' && pageNo === 1) return true;
    if (t === 'rest' && pageNo >= 2) return true;
    if (t === 'odd' && pageNo % 2 === 1) return true;
    if (t === 'even' && pageNo % 2 === 0) return true;
    const plusMatch = /^(\d+)\+$/.exec(t);
    if (plusMatch && pageNo >= Number(plusMatch[1])) return true;
    const rangeMatch = /^(\d+)\s*-\s*(\d+)$/.exec(t);
    if (rangeMatch) {
      const a = Number(rangeMatch[1]);
      const b = Number(rangeMatch[2]);
      if (pageNo >= a && pageNo <= b) return true;
    }
    if (/^\d+$/.test(t) && pageNo === Number(t)) return true;
  }
  return false;
}

/**
 * Resolve the effective PageRuleOverride for a given 0-based pageIndex (client-side preview helper).
 * Aligns custom fallback with backend `resolve_page_rule` (`default` -> `rest_pages`).
 */
export function resolvePageRuleForIndex(
  rules: PageRulesConfig | undefined,
  pageIndex: number,
): PageRuleOverride | null {
  if (!rules) return null;
  const pageNo = pageIndex + 1;
  switch (rules.strategy) {
    case 'uniform':
      return rules.uniform;
    case 'first_and_rest':
      return pageIndex === 0 ? rules.first_page : rules.rest_pages;
    case 'odd_even':
      return pageNo % 2 === 1 ? rules.odd_pages : rules.even_pages;
    case 'custom': {
      const entries = Object.entries(rules.custom_pages || {});
      if (rules.custom_pages[String(pageNo)]) {
        return rules.custom_pages[String(pageNo)];
      }
      for (const [sel, rule] of entries) {
        const s = sel.trim();
        const plusMatch = /^(\d+)\+$/.exec(s);
        if (plusMatch && pageNo >= Number(plusMatch[1])) {
          return rule;
        }
        const rangeMatch = /^(\d+)\s*-\s*(\d+)$/.exec(s);
        if (rangeMatch) {
          const a = Number(rangeMatch[1]);
          const b = Number(rangeMatch[2]);
          if (pageNo >= a && pageNo <= b) return rule;
        }
      }
      return rules.custom_pages['default'] ?? rules.rest_pages;
    }
    default:
      return rules.uniform;
  }
}
