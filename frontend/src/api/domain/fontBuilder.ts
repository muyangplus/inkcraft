// Font Builder (Local GPU/CPU & Google Colab Cloud) API types.

export type FontBuilderModeId = 'local_gpu' | 'local_cpu' | 'colab_cloud';
export type FontBuilderEngine = 'auto' | 'local_gpu' | 'local_cpu';
export type SheetPreset = 'quick' | 'standard' | 'custom';
export type FontTargetPreset = 'quick' | 'standard' | 'scanned_only';

export interface FontBuilderModeInfo {
  id: FontBuilderModeId;
  available: boolean;
  label: string;
  description: string;
}

export interface FontBuilderCapabilities {
  cuda_available: boolean;
  gpu_name: string | null;
  vram_mb: number | null;
  torch_available: boolean;
  cv2_available: boolean;
  recommended_mode: FontBuilderModeId;
  modes: FontBuilderModeInfo[];
}

export interface GenerateSheetRequest {
  preset: SheetPreset;
  custom_chars?: string;
  grid_color?: 'cyan' | 'red';
}

export interface GenerateSheetResponse {
  sheet_id: string;
  page_count: number;
  char_count: number;
  pdf_url: string;
  manifest_url: string;
}

export interface FontBuildResponse {
  task_id: string;
  engine_selected: 'local_gpu' | 'local_cpu';
}
