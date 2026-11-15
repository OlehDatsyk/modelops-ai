export type Provider = 'openai' | 'anthropic' | 'gemini'
export const PROVIDERS: Provider[] = ['openai', 'anthropic', 'gemini']

export interface User {
  id: string
  email: string
  full_name: string
  created_at: string
  last_login_at: string | null
  password_changed_at: string | null
}

export interface TokenResponse {
  access_token: string
  expires_in: number
  user: User
}

export interface SessionInfo {
  id: string
  user_agent: string
  created_at: string
  last_used_at: string
  expires_at: string
  current: boolean
}

export interface Credential {
  id: string
  provider: Provider
  key_hint: string
  status: 'unverified' | 'valid' | 'invalid' | 'error'
  status_message: string
  available_models: string[]
  last_validated_at: string | null
  created_at: string
  updated_at: string
}

export interface ProviderStatus {
  provider: Provider
  display_name: string
  configured: boolean
  credential: Credential | null
}

export interface ProjectStats {
  requests_30d: number
  errors_30d: number
  tokens_30d: number
  cost_30d_usd: number
  last_request_at: string | null
}

export interface Project {
  id: string
  name: string
  description: string
  allowed_providers: Provider[]
  created_at: string
  updated_at: string
  active_keys: number
  stats: ProjectStats | null
}

export interface ApiKey {
  id: string
  name: string
  prefix: string
  created_at: string
  last_used_at: string | null
  revoked_at: string | null
}

export interface ApiKeyCreated extends ApiKey {
  key: string
}

export interface SummaryMetrics {
  total_requests: number
  successful_requests: number
  failed_requests: number
  error_rate: number
  input_tokens: number
  output_tokens: number
  total_tokens: number
  estimated_cost_usd: number
  avg_latency_ms: number | null
  unpriced_requests: number
}

export interface TimePoint {
  bucket: string
  requests: number
  errors: number
  error_rate: number
  input_tokens: number
  output_tokens: number
  cost_usd: number
  avg_latency_ms: number | null
}

export interface BreakdownRow {
  provider?: Provider
  model?: string
  project_id?: string | null
  project_name?: string
  requests: number
  errors: number
  error_rate: number
  input_tokens: number
  output_tokens: number
  total_tokens: number
  estimated_cost_usd: number
  avg_latency_ms: number | null
  unpriced_requests: number
  request_share: number
  cost_share: number
}

export interface RangeInfo {
  start: string
  end: string
  granularity: 'hour' | 'day'
}

export interface Overview {
  range: RangeInfo
  summary: { current: SummaryMetrics; previous: SummaryMetrics }
  timeseries: TimePoint[]
  by_provider: BreakdownRow[]
  by_model: BreakdownRow[]
  by_project: BreakdownRow[]
}

export interface CostReport {
  range: RangeInfo
  total_usd: number
  previous_total_usd: number
  unpriced_requests: number
  trend: { bucket: string; cost_usd: number }[]
  by_provider: BreakdownRow[]
  by_model: BreakdownRow[]
  by_project: BreakdownRow[]
  summaries: {
    daily: { day: string; cost_usd: number; requests: number; tokens: number }[]
    monthly: { month: string; cost_usd: number; requests: number; tokens: number }[]
    today_usd: number
    month_to_date_usd: number
  }
}

export interface RequestRow {
  id: string
  request_id: string
  created_at: string
  provider: Provider
  model: string
  endpoint: string
  project_id: string | null
  project_name: string | null
  streamed: boolean
  status: 'success' | 'error'
  http_status: number
  error_type: string | null
  error_message: string | null
  input_tokens: number
  output_tokens: number
  total_tokens: number
  latency_ms: number
  cost_total_usd: string | null
  cost_status: 'estimated' | 'unknown'
}

export interface RequestDetail extends RequestRow {
  cost_input_usd: string | null
  cost_output_usd: string | null
  pricing_model_key: string | null
  input_price_per_mtok: string | null
  output_price_per_mtok: string | null
  pricing_verified: boolean
  api_key_id: string | null
}

export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface Pricing {
  id: string
  provider: Provider
  model: string
  input_price_per_mtok: string
  output_price_per_mtok: string
  currency: string
  source: string
  verified: boolean
  notes: string
  scope: 'catalog' | 'custom'
  updated_at: string
}

export interface CostPreview {
  provider: Provider
  model: string
  input_tokens: number
  output_tokens: number
  matched_pricing: Pricing | null
  input_cost_usd: string | null
  output_cost_usd: string | null
  total_cost_usd: string | null
  status: 'estimated' | 'unknown'
}

export interface Budget {
  id: string
  name: string
  project_id: string | null
  period: 'daily' | 'monthly'
  limit_usd: string
  warning_thresholds: number[]
  enforce_limit: boolean
  enabled: boolean
  created_at: string
  current_spend_usd: string
  percent_used: number
  period_start: string
}

export type AlertMetric = 'error_rate' | 'request_volume' | 'token_usage' | 'spend'

export interface AlertRule {
  id: string
  name: string
  project_id: string | null
  metric: AlertMetric
  threshold: string
  window_minutes: number
  min_requests: number
  cooldown_minutes: number
  enabled: boolean
  last_triggered_at: string | null
  created_at: string
}

export interface Notification {
  id: string
  kind: 'budget' | 'alert' | 'system'
  severity: 'info' | 'warning' | 'critical'
  title: string
  message: string
  data: Record<string, unknown>
  read_at: string | null
  created_at: string
}

export interface NotificationList {
  items: Notification[]
  unread: number
  total: number
}

export interface AnalystEvidence {
  tool: string
  args: Record<string, unknown>
  result: Record<string, unknown>
}

export interface AnalystMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  tool_results: AnalystEvidence[]
  created_at: string
}

export interface Conversation {
  id: string
  title: string
  created_at: string
  updated_at: string
}

export interface ConversationDetail extends Conversation {
  messages: AnalystMessage[]
}

export interface AnalystStatus {
  configured: boolean
  provider: string | null
  model: string | null
}
