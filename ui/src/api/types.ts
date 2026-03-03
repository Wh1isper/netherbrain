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
  temperature?: number | null;
  max_tokens?: number | null;
  context_window?: number | null;
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
  video_understanding_model?: string | null;
}

export interface McpServerSpec {
  name: string;
  transport: string;
  url?: string | null;
  env?: Record<string, string> | null;
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
  status: SessionStatus;
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
  media_type?: string;
}

export interface TurnResponse {
  session_id: string;
  input: InputPart[] | null;
  final_message: string | null;
  created_at: string;
}

// -- Run request -------------------------------------------------------------

export interface ConversationRunRequest {
  conversation_id?: string | null;
  preset_id?: string | null;
  workspace_id?: string | null;
  project_ids?: string[] | null;
  metadata?: Record<string, unknown> | null;
  input?: InputPart[] | null;
  transport?: Transport;
}

export interface SteerRequest {
  input: InputPart[];
}

// -- Toolsets (capability discovery) ----------------------------------------

export interface ToolsetInfo {
  name: string;
  description: string;
  tools: string[];
  is_alias: boolean;
}

// -- Paginated list ----------------------------------------------------------

export interface ListResponse<T> {
  items: T[];
  total: number;
}
