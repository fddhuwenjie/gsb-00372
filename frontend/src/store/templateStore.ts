import { create } from 'zustand';
import type {
  QueryTemplate, TemplateParameter, QueryResult, QueryStructure,
  ParameterizeSpec, SchemaMigrationRef,
} from '@/types';
import {
  getTemplates, createTemplate, updateTemplate, deleteTemplate,
  instantiateTemplate, parameterizeQuery, shareTemplate, checkTemplateSchema,
} from '@/services/api';

interface TemplateState {
  templates: QueryTemplate[];
  isLoading: boolean;
  activeTemplate: QueryTemplate | null;
  // Parameter values entered in the run form, keyed by parameter name.
  paramValues: Record<string, any>;
  selectedVersion: number | null;
  instanceResult: QueryResult | null;
  isRunning: boolean;
  error: string | null;
  migration: SchemaMigrationRef[] | null;

  loadTemplates: () => Promise<void>;
  selectTemplate: (template: QueryTemplate | null) => void;
  setSelectedVersion: (version: number | null) => void;
  setParamValue: (name: string, value: any) => void;
  resetParamValues: (params: TemplateParameter[]) => void;

  saveAsTemplate: (
    name: string,
    description: string,
    query_structure: QueryStructure,
    specs: ParameterizeSpec[]
  ) => Promise<QueryTemplate>;
  removeTemplate: (id: number) => Promise<void>;
  runActiveTemplate: () => Promise<void>;
  shareActiveTemplate: (expiresInHours?: number) => Promise<{ token: string; url: string } | null>;
  checkActiveSchema: () => Promise<void>;
}

/** Seed the form with declared defaults so required fields with defaults are
 *  pre-filled and list params start as arrays. */
function defaultsFor(params: TemplateParameter[]): Record<string, any> {
  const values: Record<string, any> = {};
  for (const p of params) {
    if (p.default !== undefined && p.default !== null) {
      values[p.name] = p.default;
    } else if (p.type === 'list') {
      values[p.name] = [];
    }
  }
  return values;
}

export const useTemplateStore = create<TemplateState>((set, get) => ({
  templates: [],
  isLoading: false,
  activeTemplate: null,
  paramValues: {},
  selectedVersion: null,
  instanceResult: null,
  isRunning: false,
  error: null,
  migration: null,

  loadTemplates: async () => {
    set({ isLoading: true, error: null });
    try {
      const templates = await getTemplates();
      set({ templates, isLoading: false });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : 'Failed to load templates', isLoading: false });
    }
  },

  selectTemplate: (template) => {
    set({
      activeTemplate: template,
      selectedVersion: template ? template.current_version : null,
      paramValues: template ? defaultsFor(template.parameters) : {},
      instanceResult: null,
      error: null,
      migration: null,
    });
  },

  setSelectedVersion: (version) => set({ selectedVersion: version }),

  setParamValue: (name, value) =>
    set((state) => ({ paramValues: { ...state.paramValues, [name]: value } })),

  resetParamValues: (params) => set({ paramValues: defaultsFor(params) }),

  saveAsTemplate: async (name, description, query_structure, specs) => {
    // Derive the template definition on the backend (values-only placeholders).
    const def = await parameterizeQuery(query_structure, specs);
    const created = await createTemplate({
      name, description,
      query_structure: def.queryStructure,
      parameters: def.parameters,
    });
    await get().loadTemplates();
    return created;
  },

  removeTemplate: async (id) => {
    await deleteTemplate(id);
    if (get().activeTemplate?.id === id) {
      set({ activeTemplate: null, instanceResult: null });
    }
    await get().loadTemplates();
  },

  runActiveTemplate: async () => {
    const { activeTemplate, paramValues, selectedVersion } = get();
    if (!activeTemplate) return;
    set({ isRunning: true, error: null, migration: null });
    try {
      const result = await instantiateTemplate(activeTemplate.id, paramValues, {
        version: selectedVersion ?? undefined,
      });
      set({ instanceResult: result, isRunning: false });
    } catch (err: any) {
      set({
        error: err?.message || 'Failed to run template',
        migration: err?.migration || null,
        isRunning: false,
        instanceResult: null,
      });
    }
  },

  shareActiveTemplate: async (expiresInHours) => {
    const { activeTemplate } = get();
    if (!activeTemplate) return null;
    return await shareTemplate(activeTemplate.id, expiresInHours);
  },

  checkActiveSchema: async () => {
    const { activeTemplate } = get();
    if (!activeTemplate) return;
    const res = await checkTemplateSchema(activeTemplate.id);
    set({ migration: res.ok ? [] : res.migration, error: res.ok ? null : (res.error || null) });
  },
}));
