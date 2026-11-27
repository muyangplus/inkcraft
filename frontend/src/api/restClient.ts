import type {
  ApiErrorEnvelope,
  BackgroundTemplate,
  CommitImportRequest,
  CommitImportResponse,
  DocBlock,
  DocumentDetail,
  FontBuilderCapabilities,
  FontBuildResponse,
  GenerateSheetRequest,
  GenerateSheetResponse,
  GlyphVariantsResponse,
  HealthResponse,
  HwFontMeta,
  ImportPreviewManifest,
  JobDetail,
  JobState,
  GrblSettingsResponse,
  LayoutConfig,
  LayoutDetail,
  LayoutPreset,
  MachineProfile,
  MachineState,
  PagePathsJson,
  SerialPortInfo,
  TaskStatus,
  Vec3,
  WriterCoverageResponse,
  WritersListResponse,
} from './types';

const API_BASE = '/api/v1';

export class ApiError extends Error {
  status: number;
  code: string;
  details?: Record<string, unknown> | null;

  constructor(status: number, code: string, message: string, details?: Record<string, unknown> | null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

async function parseError(res: Response): Promise<ApiError> {
  try {
    const body = (await res.json()) as Partial<ApiErrorEnvelope> & { detail?: string };
    if (body.error) {
      return new ApiError(res.status, body.error.code, body.error.message, body.error.details);
    }
    if (typeof body.detail === 'string') {
      return new ApiError(res.status, `HTTP_${res.status}`, body.detail);
    }
  } catch {
    // ignore JSON parse failure
  }
  return new ApiError(res.status, `HTTP_${res.status}`, res.statusText || `HTTP ${res.status}`);
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!(init?.body instanceof FormData) && init?.body !== undefined && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!res.ok) {
    throw await parseError(res);
  }
  return (await res.json()) as T;
}

export interface F32PathResponse {
  buffer: ArrayBuffer;
  widthMm: number;
  heightMm: number;
  bbox: [number, number, number, number];
  strokeCount: number;
  segCount: number;
}

function parseBboxHeader(raw: string | null): [number, number, number, number] {
  if (!raw) return [0, 0, 0, 0];
  const parts = raw.split(',').map((s) => Number(s.trim()));
  if (parts.length === 4 && parts.every((n) => Number.isFinite(n))) {
    return [parts[0], parts[1], parts[2], parts[3]];
  }
  return [0, 0, 0, 0];
}

export const restClient = {
  // System & Tasks
  health(): Promise<HealthResponse> {
    return requestJson<HealthResponse>('/health');
  },

  getTask(taskId: string): Promise<TaskStatus> {
    return requestJson<TaskStatus>(`/tasks/${encodeURIComponent(taskId)}`);
  },

  // Writers
  listWriters(): Promise<WritersListResponse> {
    return requestJson<WritersListResponse>('/writers');
  },

  getActiveWriter(): Promise<{ writer: HwFontMeta | null }> {
    return requestJson<{ writer: HwFontMeta | null }>('/writers/active');
  },

  setActiveWriter(writerId: string): Promise<{ active_writer_id: string }> {
    return requestJson<{ active_writer_id: string }>('/writers/active', {
      method: 'POST',
      body: JSON.stringify({ writer_id: writerId }),
    });
  },

  uploadWriter(file: File): Promise<{ writer?: HwFontMeta; task_id?: string }> {
    const fd = new FormData();
    fd.append('file', file);
    return requestJson<{ writer?: HwFontMeta; task_id?: string }>('/writers', {
      method: 'POST',
      body: fd,
    });
  },

  deleteWriter(writerId: string): Promise<{ deleted: boolean }> {
    return requestJson<{ deleted: boolean }>(`/writers/${encodeURIComponent(writerId)}`, {
      method: 'DELETE',
    });
  },

  getWriterGlyph(writerId: string, char: string, allVariants = true): Promise<GlyphVariantsResponse> {
    const q = allVariants ? '?all_variants=1' : '';
    return requestJson<GlyphVariantsResponse>(
      `/writers/${encodeURIComponent(writerId)}/glyphs/${encodeURIComponent(char)}${q}`,
    );
  },

  getWriterCoverage(writerId: string, docId?: string): Promise<WriterCoverageResponse> {
    const q = docId ? `?doc_id=${encodeURIComponent(docId)}` : '';
    return requestJson<WriterCoverageResponse>(
      `/writers/${encodeURIComponent(writerId)}/coverage${q}`,
    );
  },

  // Documents
  async listDocuments(): Promise<DocumentDetail[]> {
    const data = await requestJson<DocumentDetail[] | { documents: DocumentDetail[] }>('/documents');
    return Array.isArray(data) ? data : data.documents ?? [];
  },

  uploadDocument(file: File, modeHint?: 'reflow' | 'overlay'): Promise<{ doc_id: string; task_id?: string }> {
    const fd = new FormData();
    fd.append('file', file);
    if (modeHint) fd.append('mode_hint', modeHint);
    return requestJson<{ doc_id: string; task_id?: string }>('/documents', {
      method: 'POST',
      body: fd,
    });
  },

  previewDocument(file: File): Promise<ImportPreviewManifest> {
    const fd = new FormData();
    fd.append('file', file);
    return requestJson<ImportPreviewManifest>('/documents/preview', {
      method: 'POST',
      body: fd,
    });
  },

  getPreviewThumbUrl(previewId: string, pageIndex: number, dpi: 96 | 150 = 96): string {
    return `${API_BASE}/documents/preview/${encodeURIComponent(previewId)}/pages/${pageIndex}/thumb?dpi=${dpi}`;
  },

  commitDocumentPreview(previewId: string, payload: CommitImportRequest): Promise<CommitImportResponse> {
    return requestJson<CommitImportResponse>(
      `/documents/preview/${encodeURIComponent(previewId)}/commit`,
      {
        method: 'POST',
        body: JSON.stringify(payload),
      },
    );
  },

  cancelDocumentPreview(previewId: string): Promise<{ deleted: boolean; preview_id: string }> {
    return requestJson<{ deleted: boolean; preview_id: string }>(
      `/documents/preview/${encodeURIComponent(previewId)}`,
      { method: 'DELETE' },
    );
  },

  renameDocument(docId: string, filename: string): Promise<{ doc_id: string; filename: string }> {
    return requestJson<{ doc_id: string; filename: string }>(
      `/documents/${encodeURIComponent(docId)}`,
      {
        method: 'PATCH',
        body: JSON.stringify({ filename }),
      },
    );
  },

  deleteDocument(docId: string): Promise<{ deleted: boolean; doc_id: string }> {
    return requestJson<{ deleted: boolean; doc_id: string }>(
      `/documents/${encodeURIComponent(docId)}`,
      { method: 'DELETE' },
    );
  },

  createTextDocument(title: string, text: string): Promise<DocumentDetail & { doc_id: string }> {
    return requestJson<DocumentDetail & { doc_id: string }>('/documents/text', {
      method: 'POST',
      body: JSON.stringify({ title, text }),
    });
  },

  getDocument(docId: string): Promise<DocumentDetail> {
    return requestJson<DocumentDetail>(`/documents/${encodeURIComponent(docId)}`);
  },

  getDocumentBlocks(docId: string, pageIndex?: number): Promise<{ doc_id: string; blocks: DocBlock[] }> {
    const q = pageIndex !== undefined ? `?page_index=${pageIndex}` : '';
    return requestJson<{ doc_id: string; blocks: DocBlock[] }>(
      `/documents/${encodeURIComponent(docId)}/blocks${q}`,
    );
  },

  getDocumentMarkdown(docId: string): Promise<{ doc_id: string; sha256: string; markdown: string }> {
    return requestJson<{ doc_id: string; sha256: string; markdown: string }>(
      `/documents/${encodeURIComponent(docId)}/markdown`,
    );
  },

  getDocumentMarkdownDownloadUrl(docId: string): string {
    return `${API_BASE}/documents/${encodeURIComponent(docId)}/markdown?download=true`;
  },

  updateDocumentMarkdown(
    docId: string,
    markdown: string,
  ): Promise<{ doc_id: string; sha256: string; markdown: string; blocks: DocBlock[] }> {
    return requestJson<{ doc_id: string; sha256: string; markdown: string; blocks: DocBlock[] }>(
      `/documents/${encodeURIComponent(docId)}/markdown`,
      {
        method: 'PUT',
        body: JSON.stringify({ markdown }),
      },
    );
  },

  replaceDocumentBlocks(
    docId: string,
    blocks: DocBlock[],
  ): Promise<{ doc_id: string; sha256: string; markdown: string; blocks: DocBlock[] }> {
    return requestJson<{ doc_id: string; sha256: string; markdown: string; blocks: DocBlock[] }>(
      `/documents/${encodeURIComponent(docId)}/blocks`,
      {
        method: 'PUT',
        body: JSON.stringify({ blocks }),
      },
    );
  },

  patchDocumentBlock(
    docId: string,
    blockId: string,
    patch: Record<string, unknown>,
  ): Promise<{ doc_id: string; sha256: string; block: DocBlock; markdown: string }> {
    return requestJson<{ doc_id: string; sha256: string; block: DocBlock; markdown: string }>(
      `/documents/${encodeURIComponent(docId)}/blocks/${encodeURIComponent(blockId)}`,
      {
        method: 'PATCH',
        body: JSON.stringify(patch),
      },
    );
  },

  applyGlobalImageStyle(
    docId: string,
    imageRenderMode: string,
  ): Promise<{ doc_id: string; sha256: string; updated_count: number; blocks: DocBlock[]; markdown: string }> {
    return requestJson<{
      doc_id: string;
      sha256: string;
      updated_count: number;
      blocks: DocBlock[];
      markdown: string;
    }>(`/documents/${encodeURIComponent(docId)}/blocks/apply-image-style`, {
      method: 'POST',
      body: JSON.stringify({ image_render_mode: imageRenderMode }),
    });
  },

  recognizeFormulaBlock(
    docId: string,
    blockId: string,
  ): Promise<{ doc_id: string; sha256: string; block: DocBlock; markdown: string }> {
    return requestJson<{ doc_id: string; sha256: string; block: DocBlock; markdown: string }>(
      `/documents/${encodeURIComponent(docId)}/blocks/${encodeURIComponent(blockId)}/recognize-formula`,
      { method: 'POST' },
    );
  },

  uploadDocumentAsset(
    docId: string,
    file: File,
  ): Promise<{ doc_id: string; asset_name: string; url: string; width_mm: number; height_mm: number }> {
    const fd = new FormData();
    fd.append('file', file);
    return requestJson<{
      doc_id: string;
      asset_name: string;
      url: string;
      width_mm: number;
      height_mm: number;
    }>(`/documents/${encodeURIComponent(docId)}/assets`, {
      method: 'POST',
      body: fd,
    });
  },

  getDocumentAssetUrl(docId: string, assetName: string): string {
    return `${API_BASE}/documents/${encodeURIComponent(docId)}/assets/${encodeURIComponent(assetName)}`;
  },

  getPageImageUrl(docId: string, pageIndex: number): string {
    return `${API_BASE}/documents/${encodeURIComponent(docId)}/pages/${pageIndex}/image`;
  },

  // Backgrounds
  listBackgrounds(): Promise<{ backgrounds: BackgroundTemplate[] }> {
    return requestJson<{ backgrounds: BackgroundTemplate[] }>('/backgrounds');
  },

  uploadBackground(payload: {
    file: File;
    name?: string;
    width_mm?: number;
    height_mm?: number;
    margin_top?: number;
    margin_right?: number;
    margin_bottom?: number;
    margin_left?: number;
  }): Promise<{ background: BackgroundTemplate }> {
    const fd = new FormData();
    fd.append('file', payload.file);
    if (payload.name !== undefined) fd.append('name', payload.name);
    if (payload.width_mm !== undefined) fd.append('width_mm', String(payload.width_mm));
    if (payload.height_mm !== undefined) fd.append('height_mm', String(payload.height_mm));
    if (payload.margin_top !== undefined) fd.append('margin_top', String(payload.margin_top));
    if (payload.margin_right !== undefined) fd.append('margin_right', String(payload.margin_right));
    if (payload.margin_bottom !== undefined) fd.append('margin_bottom', String(payload.margin_bottom));
    if (payload.margin_left !== undefined) fd.append('margin_left', String(payload.margin_left));
    return requestJson<{ background: BackgroundTemplate }>('/backgrounds', {
      method: 'POST',
      body: fd,
    });
  },

  getBackgroundImageUrl(backgroundId: string): string {
    return `${API_BASE}/backgrounds/${encodeURIComponent(backgroundId)}/image`;
  },

  deleteBackground(backgroundId: string): Promise<{ deleted: boolean; background_id: string }> {
    return requestJson<{ deleted: boolean; background_id: string }>(
      `/backgrounds/${encodeURIComponent(backgroundId)}`,
      { method: 'DELETE' },
    );
  },

  // Layouts & Presets
  listLayoutPresets(): Promise<{ presets: LayoutPreset[] }> {
    return requestJson<{ presets: LayoutPreset[] }>('/layout/presets');
  },

  getLayoutDefaults(docId?: string): Promise<{ config: LayoutConfig }> {
    const q = docId ? `?doc_id=${encodeURIComponent(docId)}` : '';
    return requestJson<{ config: LayoutConfig }>(`/layout/defaults${q}`);
  },

  createLayout(
    docId: string | null,
    writerId: string | null,
    config: LayoutConfig,
  ): Promise<{ layout_id: string; task_id?: string }> {
    return requestJson<{ layout_id: string; task_id?: string }>('/layouts', {
      method: 'POST',
      body: JSON.stringify({ doc_id: docId, writer_id: writerId, config }),
    });
  },

  getLayout(layoutId: string): Promise<LayoutDetail> {
    return requestJson<LayoutDetail>(`/layouts/${encodeURIComponent(layoutId)}`);
  },

  previewMath(req: {
    latex: string;
    writer_id?: string | null;
    font_size_mm?: number;
    formula_scale?: number;
    inner_row_spacing?: number;
    display?: boolean;
  }): Promise<import('./types').MathPreviewResponse> {
    return requestJson<import('./types').MathPreviewResponse>('/math/preview', {
      method: 'POST',
      body: JSON.stringify(req),
    });
  },

  async getPagePathsF32(layoutId: string, pageIndex: number): Promise<F32PathResponse> {
    const res = await fetch(
      `${API_BASE}/layouts/${encodeURIComponent(layoutId)}/pages/${pageIndex}/paths?format=f32`,
    );
    if (!res.ok) {
      throw await parseError(res);
    }
    const buffer = await res.arrayBuffer();
    return {
      buffer,
      widthMm: Number(res.headers.get('X-Page-Width-Mm') ?? 210),
      heightMm: Number(res.headers.get('X-Page-Height-Mm') ?? 297),
      bbox: parseBboxHeader(res.headers.get('X-Bbox')),
      strokeCount: Number(res.headers.get('X-Stroke-Count') ?? 0),
      segCount: Number(res.headers.get('X-Seg-Count') ?? 0),
    };
  },

  getPagePathsJson(layoutId: string, pageIndex: number): Promise<PagePathsJson> {
    return requestJson<PagePathsJson>(
      `/layouts/${encodeURIComponent(layoutId)}/pages/${pageIndex}/paths?format=json`,
    );
  },

  async getPageGcode(layoutId: string, pageIndex: number): Promise<string> {
    const res = await fetch(
      `${API_BASE}/layouts/${encodeURIComponent(layoutId)}/pages/${pageIndex}/gcode`,
    );
    if (!res.ok) {
      throw await parseError(res);
    }
    return res.text();
  },

  getPageGcodeUrl(layoutId: string, pageIndex: number): string {
    return `${API_BASE}/layouts/${encodeURIComponent(layoutId)}/pages/${pageIndex}/gcode`;
  },

  // Machine / GRBL
  listPorts(): Promise<{ ports: SerialPortInfo[] }> {
    return requestJson<{ ports: SerialPortInfo[] }>('/machine/ports');
  },

  listProfiles(): Promise<{ active_profile_id: string; profiles: MachineProfile[] }> {
    return requestJson<{ active_profile_id: string; profiles: MachineProfile[] }>('/machine/profiles');
  },

  updateProfile(profileId: string, profile: MachineProfile): Promise<{ profile: MachineProfile }> {
    return requestJson<{ profile: MachineProfile }>(
      `/machine/profiles/${encodeURIComponent(profileId)}`,
      {
        method: 'PUT',
        body: JSON.stringify(profile),
      },
    );
  },

  getGrblSettings(): Promise<GrblSettingsResponse> {
    return requestJson<GrblSettingsResponse>('/machine/grbl-settings');
  },

  /** Write firmware `$N=value` parameters; returns the re-read `$$` table. */
  writeGrblSettings(
    settings: Record<string, number>,
  ): Promise<{ written: string[]; settings: Record<string, number> }> {
    return requestJson('/machine/grbl-settings', {
      method: 'PUT',
      body: JSON.stringify({ settings }),
    });
  },

  runMachineMacro(index: number): Promise<{ macro: string; lines: string[]; responses: string[] }> {
    return requestJson(`/machine/macros/${index}/run`, { method: 'POST' });
  },

  saveLayoutPreset(preset: LayoutPreset): Promise<{ preset: LayoutPreset }> {
    return requestJson(`/layout/presets/${encodeURIComponent(preset.preset_id)}`, {
      method: 'PUT',
      body: JSON.stringify(preset),
    });
  },

  deleteLayoutPreset(presetId: string): Promise<{ deleted: boolean }> {
    return requestJson(`/layout/presets/${encodeURIComponent(presetId)}`, { method: 'DELETE' });
  },

  connectMachine(payload: {
    port: string;
    baud: number;
    profile_id: string;
    mock: boolean;
  }): Promise<{
    machine_state: MachineState;
    profile_id: string;
    mock: boolean;
    port?: string;
    grbl_settings?: Record<string, number>;
  }> {
    return requestJson('/machine/connect', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  disconnectMachine(): Promise<{ machine_state: MachineState }> {
    return requestJson('/machine/disconnect', { method: 'POST' });
  },

  jogMachine(dx: number, dy: number, feed: number, dz = 0): Promise<{ accepted: boolean }> {
    return requestJson('/machine/jog', {
      method: 'POST',
      body: JSON.stringify({ dx, dy, dz, feed }),
    });
  },

  cancelJog(): Promise<{ accepted: boolean }> {
    return requestJson('/machine/jog/cancel', { method: 'POST' });
  },

  zeroMachine(axes: Array<'X' | 'Y' | 'Z'> = ['X', 'Y']): Promise<{ wpos: Vec3 }> {
    return requestJson('/machine/zero', {
      method: 'POST',
      body: JSON.stringify({ axes }),
    });
  },

  gotoZeroMachine(): Promise<{ wpos: Vec3; target: { x: number; y: number } }> {
    return requestJson('/machine/goto-zero', { method: 'POST' });
  },

  moveToMachine(
    x: number,
    y: number,
    feed?: number,
    penUp = true,
  ): Promise<{ wpos: Vec3; target: { x: number; y: number } }> {
    return requestJson('/machine/move-to', {
      method: 'POST',
      body: JSON.stringify({ x, y, feed: feed ?? null, pen_up: penUp }),
    });
  },

  moveToStartMachine(
    layoutId: string,
    pageIndex: number,
  ): Promise<{
    wpos: Vec3;
    target: { x: number; y: number };
    source: 'resume_breakpoint' | 'page_first_stroke';
    stroke_index: number;
  }> {
    return requestJson('/machine/move-to-start', {
      method: 'POST',
      body: JSON.stringify({ layout_id: layoutId, page_index: pageIndex }),
    });
  },

  homeMachine(): Promise<{ machine_state: MachineState; wpos: Vec3; mpos: Vec3 }> {
    return requestJson('/machine/home', { method: 'POST' });
  },

  sendRawCommand(command: string): Promise<{
    command: string;
    ok: boolean;
    responses: string[];
    wpos: Vec3;
  }> {
    return requestJson('/machine/raw', {
      method: 'POST',
      body: JSON.stringify({ command }),
    });
  },

  setPen(
    state: 'up' | 'down',
    overrides?: { overrideCmd?: string; overrideZMm?: number; overrideZFeed?: number },
  ): Promise<{ pen: 'up' | 'down' }> {
    return requestJson('/machine/pen', {
      method: 'POST',
      body: JSON.stringify({
        state,
        override_cmd: overrides?.overrideCmd ?? null,
        override_z_mm: overrides?.overrideZMm ?? null,
        override_z_feed: overrides?.overrideZFeed ?? null,
      }),
    });
  },

  frameCheck(
    layoutId: string,
    pageIndex: number,
  ): Promise<{ machine_state: MachineState; bbox: [number, number, number, number] }> {
    return requestJson('/machine/frame', {
      method: 'POST',
      body: JSON.stringify({ layout_id: layoutId, page_index: pageIndex }),
    });
  },

  unlockMachine(): Promise<{ machine_state: MachineState }> {
    return requestJson('/machine/unlock', { method: 'POST' });
  },

  estopMachine(): Promise<{ machine_state: MachineState }> {
    return requestJson('/machine/estop', { method: 'POST' });
  },

  // Jobs
  createJob(payload: {
    layout_id: string;
    page_indices?: number[];
    start_page_index?: number;
  }): Promise<{ job_id: string; job_state: JobState }> {
    return requestJson('/jobs', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  getJob(jobId: string): Promise<JobDetail> {
    return requestJson<JobDetail>(`/jobs/${encodeURIComponent(jobId)}`);
  },

  pauseJob(jobId: string): Promise<{ job_state: JobState; machine_state: MachineState }> {
    return requestJson(`/jobs/${encodeURIComponent(jobId)}/pause`, { method: 'POST' });
  },

  resumeJob(jobId: string): Promise<{ job_state: JobState; machine_state: MachineState }> {
    return requestJson(`/jobs/${encodeURIComponent(jobId)}/resume`, { method: 'POST' });
  },

  penChangeJob(jobId: string): Promise<{ job_state: JobState; machine_state: MachineState }> {
    return requestJson(`/jobs/${encodeURIComponent(jobId)}/pen-change`, { method: 'POST' });
  },

  paperReadyJob(jobId: string, pageIndex: number): Promise<{ job_state: JobState; page_index: number }> {
    return requestJson(`/jobs/${encodeURIComponent(jobId)}/paper-ready`, {
      method: 'POST',
      body: JSON.stringify({ page_index: pageIndex }),
    });
  },

  abortJob(jobId: string): Promise<{ job_state: JobState }> {
    return requestJson(`/jobs/${encodeURIComponent(jobId)}/abort`, { method: 'POST' });
  },

  // Font Builder (Local GPU/CPU & Google Colab Cloud)
  getFontBuilderCapabilities(): Promise<FontBuilderCapabilities> {
    return requestJson<FontBuilderCapabilities>('/font-builder/capabilities');
  },

  generateCollectionSheet(payload: GenerateSheetRequest): Promise<GenerateSheetResponse> {
    return requestJson<GenerateSheetResponse>('/font-builder/sheets', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  startLocalFontBuild(formData: FormData): Promise<FontBuildResponse> {
    return requestJson<FontBuildResponse>('/font-builder/build', {
      method: 'POST',
      body: formData,
    });
  },

  async downloadColabBundle(formData: FormData): Promise<Blob> {
    const res = await fetch(`${API_BASE}/font-builder/colab-bundle`, {
      method: 'POST',
      body: formData,
    });
    if (!res.ok) {
      throw await parseError(res);
    }
    return res.blob();
  },
};
