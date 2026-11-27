import { create } from 'zustand';
import { createComposeSlice } from './slices/composeSlice';
import { createDocumentSlice } from './slices/documentSlice';
import { createLayoutConfigSlice } from './slices/layoutConfigSlice';
import type { DocumentLayoutStoreState } from './slices/storeTypes';

export type { DocumentLayoutStoreState } from './slices/storeTypes';

export const useDocumentLayoutStore = create<DocumentLayoutStoreState>((...args) => ({
  ...createDocumentSlice(...args),
  ...createLayoutConfigSlice(...args),
  ...createComposeSlice(...args),
}));
