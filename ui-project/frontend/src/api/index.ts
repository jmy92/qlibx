// 后端 API 封装：所有与 FastAPI 后端的交互集中在此
const BASE = ''

export interface ModelParamSpec {
  label: string
  type: 'date' | 'select' | 'number'
  options?: string[]
  default: string | number
  tip: string
}

export interface ModelInfo {
  id: string
  name: string
  group: string
  description: string
  requires_gpu: boolean
  params_schema: Record<string, ModelParamSpec>
}

export interface ExperimentInfo {
  exp_id: string
  model_id: string
  status: 'pending' | 'running' | 'done' | 'failed'
  created_at: string
  returncode?: number
  log_count?: number
}

export interface ReportData {
  exp_id: string
  model_id: string
  status: string
  metrics: Record<string, number>
  raw: Record<string, number>
  error?: string
}

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail || JSON.stringify(body)
    } catch {
      /* 保留 statusText */
    }
    throw new Error(detail)
  }
  return (await res.json()) as T
}

export function fetchModels(): Promise<ModelInfo[]> {
  return fetch(`${BASE}/api/models`).then((r) => handle<ModelInfo[]>(r))
}

export function createExperiment(payload: {
  model_id: string
  params: Record<string, unknown>
}): Promise<{ exp_id: string }> {
  return fetch(`${BASE}/api/experiments`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  }).then((r) => handle<{ exp_id: string }>(r))
}

export function fetchExperiments(): Promise<ExperimentInfo[]> {
  return fetch(`${BASE}/api/experiments`).then((r) => handle<ExperimentInfo[]>(r))
}

export function fetchLogs(expId: string): Promise<{ status: string; logs: string }> {
  return fetch(`${BASE}/api/experiments/${expId}/logs`).then((r) =>
    handle<{ status: string; logs: string }>(r)
  )
}

export function fetchReport(expId: string): Promise<ReportData> {
  return fetch(`${BASE}/api/experiments/${expId}/report`).then((r) => handle<ReportData>(r))
}

export function downloadData(): Promise<{ message: string }> {
  return fetch(`${BASE}/api/data/download`, { method: 'POST' }).then((r) =>
    handle<{ message: string }>(r)
  )
}

export function fetchDataStatus(): Promise<{ ready: boolean; downloading: boolean }> {
  return fetch(`${BASE}/api/data/status`).then((r) =>
    handle<{ ready: boolean; downloading: boolean }>(r)
  )
}

export function wsLogsUrl(expId: string): string {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}/ws/logs/${expId}`
}

// ---------------------- 数据管理（按需拉取） ----------------------

export interface FieldInfo {
  key: string
  label: string
}

export interface StockBrief {
  code: string
  name: string
}

export interface OverviewData {
  dataset_dir: string
  calendar_start: string | null
  calendar_end: string | null
  trading_days: number
  stock_count: number
  stocks: { code: string; start: string; end: string }[]
  fields: string[]
  ready: boolean
}

export interface FetchJobStatus {
  job_id: string
  status: 'pending' | 'running' | 'done' | 'failed'
  total: number
  finished: number
  ok: number
  failed: string[]
  log_count: number
}

export function fetchDataFields(): Promise<{ fields: FieldInfo[] }> {
  return fetch(`${BASE}/api/data/fields`).then((r) => handle<{ fields: FieldInfo[] }>(r))
}

export function searchStocks(q: string): Promise<{ results: StockBrief[] }> {
  return fetch(`${BASE}/api/data/search?q=${encodeURIComponent(q)}`).then((r) =>
    handle<{ results: StockBrief[] }>(r)
  )
}

export function fetchOverview(): Promise<OverviewData> {
  return fetch(`${BASE}/api/data/overview`).then((r) => handle<OverviewData>(r))
}

export function startFetchJob(payload: {
  stocks: string[]
  start_date: string
  end_date: string
  fields: string[]
}): Promise<{ job_id: string }> {
  return fetch(`${BASE}/api/data/fetch`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  }).then((r) => handle<{ job_id: string }>(r))
}

export function fetchJobStatus(jobId: string): Promise<FetchJobStatus> {
  return fetch(`${BASE}/api/data/fetch/${jobId}`).then((r) => handle<FetchJobStatus>(r))
}

export function wsDataUrl(jobId: string): string {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}/ws/data/${jobId}`
}
