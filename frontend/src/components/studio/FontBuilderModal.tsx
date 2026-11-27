import React, { useEffect, useRef, useState } from 'react';
import {
  CheckCircle2,
  Cloud,
  Cpu,
  Download,
  FileArchive,
  FileText,
  Zap,
  Loader2,
  Play,
  Sparkles,
  Upload,
  X,
} from 'lucide-react';
import { restClient } from '../../api/restClient';
import type {
  FontBuilderCapabilities,
  FontBuilderEngine,
  FontTargetPreset,
  GenerateSheetResponse,
  SheetPreset,
  TaskProgressData,
} from '../../api/types';
import { useDocumentLayoutStore } from '../../stores/useDocumentLayoutStore';
import { useViewportStore } from '../../stores/useViewportStore';
import { useWriterStore } from '../../stores/useWriterStore';

type BuilderTab = 'local' | 'colab';

const BUILD_STAGES = [
  { key: 'segment', label: '扫描切分' },
  { key: 'align', label: '单线骨架对齐' },
  { key: 'synthesize', label: '风格迁移/异形生成' },
  { key: 'qc', label: '几何质检' },
  { key: 'export', label: '打包 .hwfont' },
];

export const FontBuilderModal: React.FC = () => {
  const activeModal = useViewportStore((s) => s.activeModal);
  const openModal = useViewportStore((s) => s.openModal);
  const pushToast = useViewportStore((s) => s.pushToast);

  const fontBuildTask = useWriterStore((s) => s.fontBuildTask);
  const setFontBuildTask = useWriterStore((s) => s.setFontBuildTask);
  const fetchWriters = useWriterStore((s) => s.fetchWriters);
  const selectWriter = useWriterStore((s) => s.selectWriter);
  const uploadWriterFile = useWriterStore((s) => s.uploadWriterFile);
  const composeNow = useDocumentLayoutStore((s) => s.composeNow);

  const isOpen = activeModal === 'font-builder';

  const [modeTab, setModeTab] = useState<BuilderTab>('local');
  const [caps, setCaps] = useState<FontBuilderCapabilities | null>(null);
  const [capsLoading, setCapsLoading] = useState(false);

  // Step 1: Collection Sheet Generator
  const [sheetPreset, setSheetPreset] = useState<SheetPreset>('quick');
  const [gridColor, setGridColor] = useState<'cyan' | 'red'>('cyan');
  const [customChars, setCustomChars] = useState('');
  const [generatingSheet, setGeneratingSheet] = useState(false);
  const [sheetResult, setSheetResult] = useState<GenerateSheetResponse | null>(null);

  // Step 2: Writer metadata & scans
  const [writerName, setWriterName] = useState('自定义书写人');
  const [writerAlias, setWriterAlias] = useState('手写体');
  const [styleTags, setStyleTags] = useState('行楷, 自然');
  const [engine, setEngine] = useState<FontBuilderEngine>('auto');
  const [variantsPerChar, setVariantsPerChar] = useState(3);
  const [targetPreset, setTargetPreset] = useState<FontTargetPreset>('quick');
  const [demoSynthetic, setDemoSynthetic] = useState(false);
  const [scanFiles, setScanFiles] = useState<File[]>([]);
  const [manifestFile, setManifestFile] = useState<File | null>(null);

  // Step 3: Build & Bundle states
  const [building, setBuilding] = useState(false);
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const [engineSelected, setEngineSelected] = useState<string | null>(null);
  const [buildResult, setBuildResult] = useState<{
    writer_id?: string;
    glyph_count?: number;
    variant_count?: number;
    engine_used?: string;
  } | null>(null);
  const [bundlingColab, setBundlingColab] = useState(false);
  const [colabDragOver, setColabDragOver] = useState(false);

  const scanInputRef = useRef<HTMLInputElement>(null);
  const manifestInputRef = useRef<HTMLInputElement>(null);
  const hwfontImportRef = useRef<HTMLInputElement>(null);

  // Fetch capabilities on open
  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;
    setCapsLoading(true);
    void restClient
      .getFontBuilderCapabilities()
      .then((res) => {
        if (cancelled) return;
        setCaps(res);
        if (res.recommended_mode === 'colab_cloud') {
          setEngine('local_cpu');
        } else {
          setEngine('auto');
        }
      })
      .catch(() => {
        // Backend may not have GPU info; fallback cleanly
      })
      .finally(() => {
        if (!cancelled) setCapsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [isOpen]);

  // Prevent Escape key from closing modal while a build or bundle is active
  useEffect(() => {
    if (!isOpen) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        if (!building && !bundlingColab) {
          openModal(null);
        }
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [isOpen, building, bundlingColab, openModal]);

  if (!isOpen) return null;

  const localGpuAvailable = Boolean(caps?.cuda_available && caps?.torch_available);

  const handleGenerateSheet = async () => {
    setGeneratingSheet(true);
    try {
      const res = await restClient.generateCollectionSheet({
        preset: sheetPreset,
        grid_color: gridColor,
        custom_chars: sheetPreset === 'custom' ? customChars : undefined,
      });
      setSheetResult(res);
      pushToast(`已生成 ${res.page_count} 页采集表（共 ${res.char_count} 字）`, 'success');
    } catch (err) {
      pushToast(`生成采集表失败: ${err instanceof Error ? err.message : String(err)}`, 'error');
    } finally {
      setGeneratingSheet(false);
    }
  };

  const handleStartLocalBuild = async () => {
    if (!demoSynthetic && scanFiles.length === 0) {
      pushToast('请先上传手写扫描图片，或勾选“合成样例扫描件快速体验”', 'warn');
      return;
    }
    if (!writerName.trim()) {
      pushToast('请填写书写人名称', 'warn');
      return;
    }

    setBuilding(true);
    setBuildResult(null);
    setFontBuildTask({
      task_id: 'starting',
      kind: 'font_import',
      state: 'running',
      stage: 'segment',
      pct: 5,
      message: '正在提交本机笔迹构建任务…',
    });

    try {
      const fd = new FormData();
      fd.append('writer_name', writerName.trim());
      fd.append('writer_alias', writerAlias.trim());
      fd.append('style_tags', styleTags.trim());
      fd.append('engine', engine);
      fd.append('variants_per_char', String(variantsPerChar));
      fd.append('target_preset', targetPreset);
      fd.append('demo_synthetic', demoSynthetic ? 'true' : 'false');
      if (sheetResult?.sheet_id) {
        fd.append('sheet_id', sheetResult.sheet_id);
      }
      if (manifestFile) {
        fd.append('manifest', manifestFile);
      }
      for (const f of scanFiles) {
        fd.append('files', f);
      }

      const started = await restClient.startLocalFontBuild(fd);
      setActiveTaskId(started.task_id);
      setEngineSelected(started.engine_selected);

      // Poll task status alongside WS task.progress until completion
      let buildDone = false;
      for (let i = 0; i < 600; i++) {
        const status = await restClient.getTask(started.task_id);
        const prog: TaskProgressData = {
          task_id: status.task_id,
          kind: status.kind,
          state: status.state,
          stage: status.stage,
          pct: status.pct,
          page: status.page,
          page_count: status.page_count,
          message: status.message,
        };
        setFontBuildTask(prog);

        if (status.state === 'done') {
          buildDone = true;
          const resObj = (status.result ?? {}) as {
            writer_id?: string;
            glyph_count?: number;
            variant_count?: number;
            engine_used?: string;
          };
          setBuildResult(resObj);
          await fetchWriters();
          if (resObj.writer_id) {
            await selectWriter(resObj.writer_id);
            void composeNow(resObj.writer_id);
          }
          pushToast(`本机笔迹构建完成：${writerName}（已自动导入并激活）`, 'success');
          break;
        }
        if (status.state === 'failed') {
          throw new Error(status.error || status.message || '本机笔迹构建失败');
        }
        await new Promise((r) => setTimeout(r, 400));
      }
      if (!buildDone) {
        throw new Error('本机笔迹构建超时，请检查后台任务状态');
      }
    } catch (err) {
      pushToast(`本机构建失败: ${err instanceof Error ? err.message : String(err)}`, 'error');
    } finally {
      setBuilding(false);
    }
  };

  const handleDownloadColabBundle = async () => {
    setBundlingColab(true);
    try {
      const fd = new FormData();
      fd.append('writer_name', writerName.trim() || 'ColabWriter');
      fd.append('writer_alias', writerAlias.trim());
      fd.append('style_tags', styleTags.trim());
      fd.append('variants_per_char', String(variantsPerChar));
      if (sheetResult?.sheet_id) {
        fd.append('sheet_id', sheetResult.sheet_id);
      }
      if (manifestFile) {
        fd.append('manifest', manifestFile);
      }
      for (const f of scanFiles) {
        fd.append('files', f);
      }

      const blob = await restClient.downloadColabBundle(fd);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'inkcraft_colab_bundle.zip';
      a.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
      pushToast('已打包下载 Colab 云端任务包 (inkcraft_colab_bundle.zip)', 'success');
    } catch (err) {
      pushToast(`打包 Colab 任务包失败: ${err instanceof Error ? err.message : String(err)}`, 'error');
    } finally {
      setBundlingColab(false);
    }
  };

  const handleColabHwfontImport = async (files: FileList | null) => {
    const file = files?.[0];
    if (!file) return;
    const imported = await uploadWriterFile(file);
    if (imported?.writer_id) {
      await selectWriter(imported.writer_id);
      void composeNow(imported.writer_id);
      openModal(null);
    }
  };

  const currentTask =
    fontBuildTask && (!activeTaskId || fontBuildTask.task_id === activeTaskId || fontBuildTask.task_id === 'starting')
      ? fontBuildTask
      : null;

  const currentStageIdx = currentTask
    ? currentTask.state === 'done'
      ? BUILD_STAGES.length
      : Math.max(
          0,
          BUILD_STAGES.findIndex((s) => s.key === currentTask.stage),
        )
    : -1;

  return (
    <div
      className="modal-backdrop"
      onClick={() => !building && !bundlingColab && openModal(null)}
    >
      <div className="modal-box" style={{ width: 720 }} onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div className="modal-title">
            <Sparkles size={15} style={{ color: 'var(--accent-primary)' }} />
            构建新书写人笔迹 (.hwfont) · 本机离线 / Google Colab 云端双模式
          </div>
          <button
            className="btn btn-sm"
            disabled={building || bundlingColab}
            onClick={() => openModal(null)}
          >
            <X size={13} /> 关闭
          </button>
        </div>

        <div className="modal-body" style={{ gap: 12 }}>
          {/* Mode Switcher + Live Hardware Capability Badge */}
          <div className="row-between" style={{ flexWrap: 'wrap', gap: 10 }}>
            <div className="seg-group">
              <button
                type="button"
                className={`seg-btn ${modeTab === 'local' ? 'active' : ''}`}
                onClick={() => setModeTab('local')}
              >
                <Cpu size={13} /> 本机离线构建 (Local GPU / CPU)
              </button>
              <button
                type="button"
                className={`seg-btn ${modeTab === 'colab' ? 'active' : ''}`}
                onClick={() => setModeTab('colab')}
              >
                <Cloud size={13} /> 云端构建 (Google Colab)
              </button>
            </div>

            <div className="status-pill mono" style={{ fontSize: 11 }}>
              {capsLoading ? (
                <>
                  <Loader2 size={12} className="spin" /> 检测硬件算力…
                </>
              ) : caps?.cuda_available ? (
                <>
                  <span className="led" />
                  <Zap size={12} />
                  <span>
                    {caps.gpu_name || 'NVIDIA GPU'}
                    {caps.vram_mb ? ` (${(caps.vram_mb / 1024).toFixed(1)}GB)` : ''}
                    {caps.torch_available ? ' · PyTorch 就绪' : ' · 仅 CPU'}
                  </span>
                </>
              ) : (
                <>
                  <span className="led warn" />
                  <Cpu size={12} />
                  <span>本机 CPU 风格迁移模式 · 推荐 GPU / Colab 加速</span>
                </>
              )}
            </div>
          </div>

          {/* STEP 1: Shared Collection Sheet Generator */}
          <div className="section-card">
            <div className="section-head">
              <span>步骤 1 · 生成并打印手写采集纸 (带 4 角 ArUco 定位码)</span>
              {sheetResult && (
                <span className="mono" style={{ color: 'var(--state-ready)' }}>
                  已就绪 · {sheetResult.page_count} 页 / {sheetResult.char_count} 字
                </span>
              )}
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 120px auto', gap: 8, alignItems: 'end' }}>
              <div>
                <div className="ctrl-label" style={{ marginBottom: 3 }}>
                  <span>采集字表规模 (preset)</span>
                </div>
                <select
                  value={sheetPreset}
                  onChange={(e) => setSheetPreset(e.target.value as SheetPreset)}
                >
                  <option value="quick">快速体验字表 (quick · 常用核心字)</option>
                  <option value="standard">标准扩展字表 (standard · 覆盖高频汉字与符号)</option>
                  <option value="custom">自定义字符集 (custom)</option>
                </select>
              </div>
              <div>
                <div className="ctrl-label" style={{ marginBottom: 3 }}>
                  <span>滤除参考格色</span>
                </div>
                <select
                  value={gridColor}
                  onChange={(e) => setGridColor(e.target.value as 'cyan' | 'red')}
                >
                  <option value="cyan">淡青色 (Cyan)</option>
                  <option value="red">淡红色 (Red)</option>
                </select>
              </div>
              <button
                className="btn btn-primary"
                disabled={generatingSheet}
                onClick={() => void handleGenerateSheet()}
              >
                {generatingSheet ? <Loader2 size={13} className="spin" /> : <FileText size={13} />}
                生成采集表 PDF
              </button>
            </div>

            {sheetPreset === 'custom' && (
              <input
                type="text"
                value={customChars}
                onChange={(e) => setCustomChars(e.target.value)}
                placeholder="输入需要采集的自定义字符，例如：永和九年岁在癸丑力学实验报告0123456789"
              />
            )}

            {sheetResult && (
              <div className="row-between" style={{ fontSize: 11.5, paddingTop: 2 }}>
                <span className="mono" style={{ color: 'var(--text-secondary)' }}>
                  sheet_id: {sheetResult.sheet_id}
                </span>
                <div className="row-gap">
                  <a
                    className="btn btn-xs btn-cyan"
                    href={sheetResult.pdf_url}
                    target="_blank"
                    rel="noreferrer"
                    download
                  >
                    <Download size={11} /> 下载打印 PDF
                  </a>
                  <a
                    className="btn btn-xs"
                    href={sheetResult.manifest_url}
                    target="_blank"
                    rel="noreferrer"
                    download
                  >
                    <Download size={11} /> 下载 manifest.json
                  </a>
                </div>
              </div>
            )}
          </div>

          {/* STEP 2: Writer Info & Scans */}
          <div className="section-card">
            <div className="section-head">
              <span>
                步骤 2 · 书写人信息与扫描件上传 ({modeTab === 'local' ? '本机推理' : '打包至 Colab'})
              </span>
              {modeTab === 'local' && (
                <label
                  className="row-gap"
                  style={{
                    fontSize: 11.5,
                    color: 'var(--state-warn)',
                    fontWeight: 600,
                    cursor: 'pointer',
                  }}
                >
                  <input
                    type="checkbox"
                    checked={demoSynthetic}
                    onChange={(e) => setDemoSynthetic(e.target.checked)}
                  />
                  合成样例扫描件快速体验 (免扫描直接跑通)
                </label>
              )}
            </div>

            <div className="grid-3">
              <div>
                <div className="ctrl-label" style={{ marginBottom: 3 }}>
                  <span>书写人名称 *</span>
                </div>
                <input
                  type="text"
                  value={writerName}
                  onChange={(e) => setWriterName(e.target.value)}
                  placeholder="例如：张明"
                />
              </div>
              <div>
                <div className="ctrl-label" style={{ marginBottom: 3 }}>
                  <span>笔迹别名</span>
                </div>
                <input
                  type="text"
                  value={writerAlias}
                  onChange={(e) => setWriterAlias(e.target.value)}
                  placeholder="例如：工整行书"
                />
              </div>
              <div>
                <div className="ctrl-label" style={{ marginBottom: 3 }}>
                  <span>风格标签 (逗号分隔)</span>
                </div>
                <input
                  type="text"
                  value={styleTags}
                  onChange={(e) => setStyleTags(e.target.value)}
                  placeholder="行楷, 钢笔, 清秀"
                />
              </div>
            </div>

            {modeTab === 'local' ? (
              <div className="grid-3">
                <div>
                  <div className="ctrl-label" style={{ marginBottom: 3 }}>
                    <span>计算引擎 (engine)</span>
                  </div>
                  <select
                    value={engine}
                    onChange={(e) => setEngine(e.target.value as FontBuilderEngine)}
                  >
                    <option value="auto">
                      自动选择 ({localGpuAvailable ? '优先本地 GPU' : '本机 CPU'})
                    </option>
                    <option value="local_gpu" disabled={!localGpuAvailable}>
                      本地 GPU (RTX CUDA + PyTorch){!localGpuAvailable ? ' [不可用]' : ''}
                    </option>
                    <option value="local_cpu">本地 CPU 参数化风格迁移 (免 GPU)</option>
                  </select>
                </div>
                <div>
                  <div className="ctrl-label" style={{ marginBottom: 3 }}>
                    <span>目标字库范围</span>
                  </div>
                  <select
                    value={targetPreset}
                    onChange={(e) => setTargetPreset(e.target.value as FontTargetPreset)}
                  >
                    <option value="quick">常用扩展字表 (quick)</option>
                    <option value="standard">全量标准字表 (standard)</option>
                    <option value="scanned_only">仅导出扫描字符 (scanned_only)</option>
                  </select>
                </div>
                <div>
                  <div className="ctrl-label" style={{ marginBottom: 3 }}>
                    <span>单字异形变体数</span>
                    <span className="mono">{variantsPerChar}</span>
                  </div>
                  <input
                    type="number"
                    className="mono"
                    min={1}
                    max={8}
                    value={variantsPerChar}
                    onChange={(e) =>
                      setVariantsPerChar(Math.max(1, Math.min(8, Number(e.target.value) || 3)))
                    }
                  />
                </div>
              </div>
            ) : (
              <div className="row-between" style={{ fontSize: 11.5, color: 'var(--text-secondary)' }}>
                <span>每字生成同字异形变体数 (variants_per_char)</span>
                <input
                  type="number"
                  className="mono"
                  style={{ width: 80 }}
                  min={1}
                  max={8}
                  value={variantsPerChar}
                  onChange={(e) =>
                    setVariantsPerChar(Math.max(1, Math.min(8, Number(e.target.value) || 3)))
                  }
                />
              </div>
            )}

            {!(modeTab === 'local' && demoSynthetic) && (
              <div className="grid-2">
                <div className="dropzone" onClick={() => scanInputRef.current?.click()}>
                  <Upload size={14} />
                  <span>
                    {scanFiles.length > 0
                      ? `已选 ${scanFiles.length} 张扫描图 (${scanFiles[0].name}${scanFiles.length > 1 ? ' 等' : ''})`
                      : '上传手写扫描图片 (PNG / JPG，可多选)'}
                  </span>
                  <input
                    ref={scanInputRef}
                    type="file"
                    accept="image/png,image/jpeg,image/webp"
                    multiple
                    style={{ display: 'none' }}
                    onChange={(e) => {
                      if (e.target.files) setScanFiles(Array.from(e.target.files));
                    }}
                  />
                </div>

                <div className="dropzone" onClick={() => manifestInputRef.current?.click()}>
                  <FileText size={14} />
                  <span>
                    {manifestFile
                      ? `已选 manifest: ${manifestFile.name}`
                      : sheetResult
                        ? `自动关联步骤 1 采集表 (${sheetResult.sheet_id})`
                        : '可选：上传对应 manifest.json'}
                  </span>
                  <input
                    ref={manifestInputRef}
                    type="file"
                    accept="application/json,.json"
                    style={{ display: 'none' }}
                    onChange={(e) => {
                      setManifestFile(e.target.files?.[0] ?? null);
                    }}
                  />
                </div>
              </div>
            )}
          </div>

          {/* STEP 3: Local Execution OR Cloud Bundle + Import */}
          {modeTab === 'local' ? (
            <div className="section-card">
              <div className="section-head">
                <span>步骤 3 · 本机离线训练/合成并自动导入</span>
                {engineSelected && (
                  <span className="mono" style={{ color: 'var(--accent-primary)' }}>
                    引擎: {engineSelected}
                  </span>
                )}
              </div>

              {currentTask && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
                  <div className="row-between" style={{ fontSize: 11.5 }}>
                    <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>
                      {currentTask.message || `阶段: ${currentTask.stage}`}
                    </span>
                    <span className="mono" style={{ color: 'var(--accent-primary)', fontWeight: 700 }}>
                      {Math.round(currentTask.pct)}%
                    </span>
                  </div>
                  <div className="stage-steps">
                    {BUILD_STAGES.map((st, idx) => (
                      <div
                        key={st.key}
                        className={`stage-step ${
                          idx < currentStageIdx
                            ? 'done'
                            : idx === currentStageIdx && currentTask.state === 'running'
                              ? 'active'
                              : ''
                        }`}
                        title={st.label}
                      />
                    ))}
                  </div>
                  <div className="row-between" style={{ fontSize: 10.5, color: 'var(--text-muted)' }}>
                    {BUILD_STAGES.map((st, idx) => (
                      <span
                        key={st.key}
                        style={{
                          color:
                            idx < currentStageIdx
                              ? 'var(--state-ready)'
                              : idx === currentStageIdx
                                ? 'var(--text-primary)'
                                : undefined,
                        }}
                      >
                        {st.label}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {buildResult && (
                <div
                  className="row-between"
                  style={{
                    background: 'rgba(34, 197, 94, 0.12)',
                    border: '1px solid rgba(34, 197, 94, 0.45)',
                    borderRadius: 7,
                    padding: '8px 10px',
                    fontSize: 12,
                  }}
                >
                  <span className="row-gap" style={{ color: 'var(--state-ready)', fontWeight: 600 }}>
                    <CheckCircle2 size={14} /> 构建成功并已热加载！
                  </span>
                  <span className="mono" style={{ fontSize: 11.5 }}>
                    {buildResult.glyph_count ?? 0} 字 · {buildResult.variant_count ?? 0} 变体 ·{' '}
                    {buildResult.engine_used ?? engineSelected}
                  </span>
                </div>
              )}

              <button
                className="btn btn-primary"
                style={{ width: '100%', height: 36 }}
                disabled={building}
                onClick={() => void handleStartLocalBuild()}
              >
                {building ? (
                  <>
                    <Loader2 size={14} className="spin" /> 正在本机构建单线笔迹…
                  </>
                ) : (
                  <>
                    <Play size={14} /> 开始本机离线构建 .hwfont
                  </>
                )}
              </button>
            </div>
          ) : (
            <div className="section-card">
              <div className="section-head">
                <span>步骤 3 · 打包上传 Google Colab GPU 并回传导入 .hwfont</span>
              </div>

              <button
                className="btn btn-primary"
                style={{ width: '100%', height: 36 }}
                disabled={bundlingColab}
                onClick={() => void handleDownloadColabBundle()}
              >
                {bundlingColab ? (
                  <Loader2 size={14} className="spin" />
                ) : (
                  <FileArchive size={14} />
                )}
                打包下载 Colab 云端任务包 (inkcraft_colab_bundle.zip)
              </button>

              <div
                style={{
                  background: 'var(--bg-input)',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: 6,
                  padding: '8px 10px',
                  fontSize: 11.5,
                  color: 'var(--text-secondary)',
                  lineHeight: 1.6,
                }}
              >
                1. 将下载的 <code className="mono">inkcraft_colab_bundle.zip</code> 上传到 Google Drive 或 Colab 会话并解压；
                <br />
                2. 在免费 T4/L4 GPU 环境下按顺序运行 <code className="mono">02_scan_to_trajectories.ipynb</code> 与{' '}
                <code className="mono">03_train_and_export.ipynb</code>；
                <br />
                3. 下载生成的 <code className="mono">.hwfont</code> 单文件并拖入下方区域即可立即切换使用：
              </div>

              <div
                className={`dropzone ${colabDragOver ? 'dragover' : ''}`}
                onClick={() => hwfontImportRef.current?.click()}
                onDragOver={(e) => {
                  e.preventDefault();
                  setColabDragOver(true);
                }}
                onDragLeave={() => setColabDragOver(false)}
                onDrop={(e) => {
                  e.preventDefault();
                  setColabDragOver(false);
                  void handleColabHwfontImport(e.dataTransfer.files);
                }}
              >
                <Upload size={14} />
                <span>拖入或点击导入从 Google Colab 导出的 .hwfont 文件</span>
                <input
                  ref={hwfontImportRef}
                  type="file"
                  accept=".hwfont"
                  style={{ display: 'none' }}
                  onChange={(e) => {
                    void handleColabHwfontImport(e.target.files);
                    e.target.value = '';
                  }}
                />
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
