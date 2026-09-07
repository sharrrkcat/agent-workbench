export type PetPosition = { mode: 'default' | 'custom'; x: number | null; y: number | null };

export type PetBubbleTexts = {
  idle: string;
  waiting: string;
  done: string;
  failed: string;
  cancelled: string;
  interrupted: string;
  wake: string;
  tuck: string;
  status: string;
  select: string;
  reload: string;
  no_pet: string;
  import_success: string;
  import_failed: string;
  delete_success: string;
  delete_failed: string;
};

export type PetSettings = {
  pet_enabled: boolean;
  default_pet_id: string;
  pet_scale: number;
  show_status_bubble: boolean;
  bubble_offset_x: number;
  bubble_offset_y: number;
  jump_on_hover: boolean;
  running_prefix: string;
  position: PetPosition;
  bubble_texts: PetBubbleTexts;
};

export type PetItem = {
  id: string;
  display_name: string;
  description?: string;
  valid: boolean;
  status?: string;
  errors?: string[];
  spritesheet_url?: string | null;
  can_delete?: boolean;
  is_builtin?: boolean;
};

export type PetSettingsResponse = { settings: PetSettings };

export type PetListResponse = { pets: PetItem[] };

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

export type PetSettingsPatch = Partial<Omit<PetSettings, 'position' | 'bubble_texts'>> & {
  position?: Partial<PetPosition>;
  bubble_texts?: Partial<PetBubbleTexts>;
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
