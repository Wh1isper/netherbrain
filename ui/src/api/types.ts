/**
 * TypeScript interfaces mirroring backend Pydantic models.
 * Only fields consumed by the UI are included.
 */

// -- Enums -------------------------------------------------------------------

export type SessionStatus =
  | "created"
  | "committed"
  | "awaiting_tool_results"
  | "failed"
  | "archived";

export type ConversationStatus = "active" | "archived";

export type Transport = "sse" | "stream";

export type SessionType = "agent" | "async_subagent";

// -- Preset ------------------------------------------------------------------

export interface ModelPreset {
  name: string;
  model_settings_preset?: string | null;
  model_settings?: Record<string, unknown> | null;
  model_config_preset?: string | null;
  model_config_overrides?: Record<string, unknown> | null;
}

export interface ToolsetSpec {
  toolset_name: string;
  enabled?: boolean;
  exclude_tools?: string[];
}

export interface EnvironmentSpec {
  mode?: "local" | "sandbox";
  workspace_id?: string | null;
  project_ids?: string[] | null;
  container_id?: string | null;
  container_workdir?: string;
}

export interface SubagentRef {
  preset_id: string;
  name: string;
  description: string;
  instruction?: string | null;
}

export interface SubagentSpec {
  include_builtin?: boolean;
  async_enabled?: boolean;
  refs?: SubagentRef[];
}

export interface ToolConfigSpec {
  skip_url_verification?: boolean;
  enable_load_document?: boolean;
  image_understanding_model?: string | null;
  image_understanding_model_settings?: Record<string, unknown> | null;
  video_understanding_model?: string | null;
  video_understanding_model_settings?: Record<string, unknown> | null;
}

export interface McpServerSpec {
  url: string;
  transport?: "streamable_http" | "sse";
  headers?: Record<string, string> | null;
  tool_prefix?: string | null;
  timeout?: number | null;
}

export interface PresetResponse {
  preset_id: string;
  name: string;
  description: string | null;
  model: ModelPreset;
  system_prompt: string;
  toolsets: ToolsetSpec[];
  environment: EnvironmentSpec;
  tool_config: ToolConfigSpec;
  subagents: SubagentSpec;
  mcp_servers: McpServerSpec[];
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export interface PresetCreate {
  preset_id?: string;
  name: string;
  description?: string | null;
  model: ModelPreset;
  system_prompt: string;
  toolsets?: ToolsetSpec[];
  environment?: EnvironmentSpec;
  tool_config?: ToolConfigSpec;
  subagents?: SubagentSpec;
  mcp_servers?: McpServerSpec[];
  is_default?: boolean;
}

export interface PresetUpdate {
  name?: string;
  description?: string | null;
  model?: ModelPreset;
  system_prompt?: string;
  toolsets?: ToolsetSpec[];
  environment?: EnvironmentSpec;
  tool_config?: ToolConfigSpec;
  subagents?: SubagentSpec;
  mcp_servers?: McpServerSpec[];
  is_default?: boolean;
}

// -- Workspace ---------------------------------------------------------------

export interface WorkspaceResponse {
  workspace_id: string;
  name: string | null;
  projects: string[];
  metadata: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface WorkspaceCreate {
  workspace_id?: string;
  name?: string | null;
  projects?: string[];
  metadata?: Record<string, unknown> | null;
}

export interface WorkspaceUpdate {
  name?: string | null;
  projects?: string[];
  metadata?: Record<string, unknown> | null;
}

// -- Conversation ------------------------------------------------------------

export interface LatestSessionInfo {
  session_id: string;
  status: SessionStatus;
  session_type: SessionType;
  project_ids: string[];
  preset_id: string | null;
  created_at: string;
}

export interface ActiveSessionInfo {
  session_id: string;
  transport: Transport;
  stream_key: string | null;
}

export interface MailboxSummary {
  pending_count: number;
}

export interface ConversationResponse {
  conversation_id: string;
  title: string | null;
  default_preset_id: string | null;
  metadata: Record<string, unknown> | null;
  status: ConversationStatus;
  created_at: string;
  updated_at: string;
}

export interface ConversationDetailResponse extends ConversationResponse {
  latest_session: LatestSessionInfo | null;
  active_session: ActiveSessionInfo | null;
  mailbox: MailboxSummary | null;
}

export interface ConversationUpdate {
  title?: string | null;
  default_preset_id?: string | null;
  metadata?: Record<string, unknown> | null;
  status?: ConversationStatus;
}

// -- Session / turns ---------------------------------------------------------

export interface InputPart {
  type: "text" | "url" | "file" | "binary";
  text?: string;
  url?: string;
  path?: string;
  data?: string;
  mime?: string;
  storage?: "ephemeral" | "persistent" | "inline";
}

export interface TurnResponse {
  session_id: string;
  input: InputPart[] | null;
  final_message: string | null;
  display_messages: DisplayEvent[] | null;
  created_at: string;
}

export interface TurnsResponse {
  turns: TurnResponse[];
  has_more: boolean;
}

// -- Display message events (compressed AG-UI chunks) -----------------------

export interface TextMessageChunk {
  type: "TEXT_MESSAGE_CHUNK";
  messageId: string;
  role: string;
  delta: string;
}

export interface ToolCallChunk {
  type: "TOOL_CALL_CHUNK";
  toolCallId: string;
  toolCallName: string;
  parentMessageId?: string;
  delta: string;
}

export interface ToolCallResultDisplay {
  type: "TOOL_CALL_RESULT";
  toolCallId: string;
  messageId: string;
  content: string;
  role: string;
  status?: string;
}

export interface ReasoningMessageChunk {
  type: "REASONING_MESSAGE_CHUNK";
  messageId: string;
  delta: string;
}

/** Discriminated union of display event types. */
export type DisplayEvent =
  | TextMessageChunk
  | ToolCallChunk
  | ToolCallResultDisplay
  | ReasoningMessageChunk
  | { type: string }; // catch-all for CUSTOM / unknown event types

// -- Run request -------------------------------------------------------------

export interface ConversationRunRequest {
  conversation_id?: string | null;
  preset_id?: string | null;
  workspace_id?: string | null;
  project_ids?: string[] | null;
  metadata?: Record<string, unknown> | null;
  config_override?: Record<string, unknown> | null;
  input?: InputPart[] | null;
  transport?: Transport;
}

export interface SteerRequest {
  input: InputPart[];
}

// -- Conversation fork/fire -------------------------------------------------

export interface ConversationForkRequest {
  preset_id: string;
  from_session_id?: string | null;
  workspace_id?: string | null;
  project_ids?: string[] | null;
  metadata?: Record<string, unknown> | null;
  config_override?: Record<string, unknown> | null;
  input?: InputPart[] | null;
  transport?: Transport;
}

export interface ConversationFireRequest {
  preset_id?: string | null;
  workspace_id?: string | null;
  project_ids?: string[] | null;
  config_override?: Record<string, unknown> | null;
  input?: InputPart[] | null;
  transport?: Transport;
}

// -- Mailbox ----------------------------------------------------------------

export interface MailboxMessageResponse {
  message_id: string;
  conversation_id: string;
  source_session_id: string;
  source_type: string;
  subagent_name: string;
  created_at: string;
  delivered_to: string | null;
}

// -- Toolsets (capability discovery) ----------------------------------------

export interface ToolsetInfo {
  name: string;
  description: string;
  tools: string[];
  is_alias: boolean;
}

// -- Model Presets (capability discovery) -----------------------------------

export interface ModelSettingsPresetInfo {
  name: string;
  settings: Record<string, unknown>;
}

export interface ModelConfigPresetInfo {
  name: string;
  config: Record<string, unknown>;
}

export interface ModelPresetsResponse {
  model_settings_presets: ModelSettingsPresetInfo[];
  model_settings_aliases: Record<string, string>;
  model_config_presets: ModelConfigPresetInfo[];
  model_config_aliases: Record<string, string>;
}

// -- Auth / Users ------------------------------------------------------------

export type UserRole = "admin" | "user";

export interface UserResponse {
  user_id: string;
  display_name: string;
  role: UserRole;
  is_active: boolean;
  must_change_password: boolean;
  created_at: string;
  updated_at: string;
}

export interface LoginRequest {
  user_id: string;
  password: string;
}

export interface LoginResponse {
  token: string;
  user: UserResponse;
}

export interface ChangePasswordRequest {
  old_password: string;
  new_password: string;
}

export interface UserCreate {
  user_id: string;
  display_name: string;
  role?: UserRole;
}

export interface UserCreateResponse {
  user: UserResponse;
  password: string;
  api_key: ApiKeyCreateResponse;
}

export interface UserUpdate {
  display_name?: string;
  role?: UserRole;
  is_active?: boolean;
}

export interface ResetPasswordResponse {
  password: string;
}

// -- API Keys ----------------------------------------------------------------

export interface ApiKeyResponse {
  key_id: string;
  key_prefix: string;
  user_id: string;
  name: string;
  is_active: boolean;
  expires_at: string | null;
  created_at: string;
}

export interface ApiKeyCreate {
  name: string;
  user_id?: string;
  expires_in_days?: number;
}

export interface ApiKeyCreateResponse {
  key_id: string;
  key: string;
  name: string;
}

// -- Paginated list ----------------------------------------------------------

export interface ListResponse<T> {
  items: T[];
  total: number;
}
