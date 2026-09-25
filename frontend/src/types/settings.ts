export type PetPosition = { mode: 'default' | 'custom'; x: number | null; y: number | null };

export type PetSettings = {
  position: PetPosition;
};

export type PetSettingsResponse = { settings: PetSettings };

export type GeneralSettings = {
  max_image_size_mb: number;
  max_file_size_mb: number;
  max_attachments_per_message: number;
  max_file_context_per_file_kb: number;
  max_total_file_context_per_message_kb: number;
  send_text_file_attachments_to_llm: boolean;
  persist_streaming_message_deltas: boolean;
  show_full_processing: boolean;
  auto_generate_session_titles: boolean;
  session_title_prompt: string;
  session_title_max_input_chars: number;
  pet: PetSettings;
  session_title_prompt_default: string;
};

export type PetSettingsPatch = {
  position?: Partial<PetPosition>;
};

export type GeneralSettingsPatch = Partial<
  Omit<
    GeneralSettings,
    | 'pet'
    | 'session_title_prompt_default'
  >
> & { pet?: PetSettingsPatch };
