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
  auto_generate_session_titles: boolean;
  session_title_prompt: string;
  session_title_max_input_chars: number;
  group_transcript_system_instruction: string | null;
  core_memory_content: string;
  core_memory_enabled: boolean;
  pet: PetSettings;
  session_title_prompt_default: string;
  group_transcript_system_instruction_default: string;
  group_transcript_system_instruction_effective: string;
};

export type PetSettingsPatch = {
  position?: Partial<PetPosition>;
};

export type GeneralSettingsPatch = Partial<
  Omit<
    GeneralSettings,
    | 'pet'
    | 'session_title_prompt_default'
    | 'group_transcript_system_instruction_default'
    | 'group_transcript_system_instruction_effective'
  >
> & { pet?: PetSettingsPatch };
