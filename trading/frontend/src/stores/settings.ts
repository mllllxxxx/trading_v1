import { create } from "zustand";
import {
  api,
  type LLMSettings,
  type DataSourceSettings,
  type UpdateLLMSettingsRequest,
  type UpdateDataSourceSettingsRequest,
} from "@/lib/api";

interface SettingsState {
  llmSettings: LLMSettings | null;
  llmLoading: boolean;
  llmError: string | null;

  dataSourceSettings: DataSourceSettings | null;
  dataSourceLoading: boolean;
  dataSourceError: string | null;

  loadLLMSettings: () => Promise<void>;
  updateLLMSettings: (settings: UpdateLLMSettingsRequest) => Promise<LLMSettings>;
  loadDataSourceSettings: () => Promise<void>;
  updateDataSourceSettings: (settings: UpdateDataSourceSettingsRequest) => Promise<DataSourceSettings>;
}

function toMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Unknown error";
}

export const useSettingsStore = create<SettingsState>((set) => ({
  llmSettings: null,
  llmLoading: false,
  llmError: null,

  dataSourceSettings: null,
  dataSourceLoading: false,
  dataSourceError: null,

  loadLLMSettings: async () => {
    set({ llmLoading: true, llmError: null });
    try {
      const llmSettings = await api.getLLMSettings();
      set({ llmSettings, llmLoading: false });
    } catch (error) {
      set({ llmError: toMessage(error), llmLoading: false });
    }
  },

  updateLLMSettings: async (settings) => {
    set({ llmLoading: true, llmError: null });
    try {
      const llmSettings = await api.updateLLMSettings(settings);
      set({ llmSettings, llmLoading: false });
      return llmSettings;
    } catch (error) {
      const message = toMessage(error);
      set({ llmError: message, llmLoading: false });
      throw error;
    }
  },

  loadDataSourceSettings: async () => {
    set({ dataSourceLoading: true, dataSourceError: null });
    try {
      const dataSourceSettings = await api.getDataSourceSettings();
      set({ dataSourceSettings, dataSourceLoading: false });
    } catch (error) {
      set({ dataSourceError: toMessage(error), dataSourceLoading: false });
    }
  },

  updateDataSourceSettings: async (settings) => {
    set({ dataSourceLoading: true, dataSourceError: null });
    try {
      const dataSourceSettings = await api.updateDataSourceSettings(settings);
      set({ dataSourceSettings, dataSourceLoading: false });
      return dataSourceSettings;
    } catch (error) {
      const message = toMessage(error);
      set({ dataSourceError: message, dataSourceLoading: false });
      throw error;
    }
  },
}));
