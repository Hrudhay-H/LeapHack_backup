import type { FarmerMe, Hotspot, SimStatus, SmsMessage, SurveyDetail, Verdict } from './types'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

interface Opts {
  method?: string
  body?: unknown
  token?: string
  headers?: Record<string, string>
}

function buildHeaders(o: Opts): Record<string, string> {
  const h: Record<string, string> = { ...(o.headers ?? {}) }
  if (o.body !== undefined) h['Content-Type'] = 'application/json'
  if (o.token) h['Authorization'] = `Bearer ${o.token}`
  return h
}

async function fail(r: Response): Promise<never> {
  let msg = r.statusText
  try {
    const j = await r.json()
    msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)
  } catch {
    /* non-JSON error body */
  }
  throw new ApiError(r.status, msg)
}

const API_BASE = (import.meta as any).env?.VITE_API_URL || ''

async function req<T>(path: string, o: Opts = {}): Promise<T> {
  const r = await fetch(`${API_BASE}/api${path}`, {
    method: o.method ?? (o.body !== undefined ? 'POST' : 'GET'),
    headers: buildHeaders(o),
    body: o.body !== undefined ? JSON.stringify(o.body) : undefined,
  })
  if (!r.ok) return fail(r)
  return r.json() as Promise<T>
}

export async function fetchBlob(path: string, o: Opts = {}): Promise<Blob> {
  const r = await fetch(`${API_BASE}/api${path}`, { headers: buildHeaders(o) })
  if (!r.ok) return fail(r)
  return r.blob()
}

export const api = {
  // Farmer (digital) portal
  farmerRequestOtp: (farmer_id: string) =>
    req<{ challenge_id: string; expires_in_s: number }>('/farmer/login/request', { body: { farmer_id } }),
  farmerVerify: (challenge_id: string, otp: string) =>
    req<{ token: string }>('/farmer/login/verify', { body: { challenge_id, otp } }),
  farmerMe: (token: string) => req<FarmerMe>('/farmer/me', { token }),
  farmerSurvey: (token: string, id: string) => req<SurveyDetail>(`/farmer/surveys/${id}`, { token }),
  farmerLayer: (token: string, id: string, name: string) => fetchBlob(`/farmer/surveys/${id}/layers/${name}`, { token }),
  farmerReport: (token: string, id: string, download: boolean) =>
    fetchBlob(`/farmer/surveys/${id}/report?download=${download}`, { token }),

  verdict: (token: string, survey: string, hotspot: string, verdict: Exclude<Verdict, null>, note = '', access?: string) =>
    req<Hotspot>(`/hotspots/${survey}/${hotspot}/verdict`, {
      token,
      body: { verdict, note },
      headers: access ? { 'X-Access-Token': access } : undefined,
    }),

  // Assisted access (operator)
  operatorLogin: (operator_id: string, pin: string) =>
    req<{ token: string; operator: { id: string; name: string; centre: string } }>('/assisted/login', {
      body: { operator_id, pin },
    }),
  lookup: (token: string, farmer_id: string) =>
    req<{
      farmer_id: string
      name: string
      village: string
      language: 'kn' | 'en'
      masked_mobile: string
      reports: { report_id: string; survey_id: string; generated_at: string; hotspots_detected: number | null }[]
    }>('/assisted/lookup', { token, body: { farmer_id } }),
  createRequest: (token: string, farmer_id: string, report_id: string) =>
    req<{ request_id: string; masked_mobile: string; expires_in_s: number }>('/assisted/requests', {
      token,
      body: { farmer_id, report_id },
    }),
  verifyRequest: (token: string, request_id: string, otp: string) =>
    req<{ access_token: string; report_id: string; expires_at: string }>(`/assisted/requests/${request_id}/verify`, {
      token,
      body: { otp },
    }),
  assistedSummary: (token: string, report_id: string, access: string) =>
    req<SurveyDetail>(`/assisted/reports/${report_id}/summary`, { token, headers: { 'X-Access-Token': access } }),
  assistedDownload: (token: string, report_id: string, access: string) =>
    fetchBlob(`/assisted/reports/${report_id}/download`, { token, headers: { 'X-Access-Token': access } }),

  // Admin / demo
  adminOverview: (key: string) =>
    req<{
      surveys: {
        survey_id: string
        farm: string
        farmer: string
        farmer_id: string
        village: string
        status: string
        hotspots: number | null
        suspicious_percent: number | null
        data_source: string
      }[]
      access_log: { report_id: string; actor_type: string; actor_id: string; access_type: string; authorization_id: string; at: string }[]
    }>('/admin/overview', { headers: { 'X-Admin-Key': key } }),
  adminSimStatus: (key: string) => req<SimStatus>('/admin/sim/status', { headers: { 'X-Admin-Key': key } }),
  adminSimStart: (key: string) => req<{ started: string[] }>('/admin/sim/start', { method: 'POST', headers: { 'X-Admin-Key': key } }),
  adminSimReset: (key: string) => req<{ reset: boolean }>('/admin/sim/reset', { method: 'POST', headers: { 'X-Admin-Key': key } }),
  adminLayer: (key: string, survey_id: string, name: string) =>
    fetchBlob(`/admin/surveys/${survey_id}/layers/${name}`, { headers: { 'X-Admin-Key': key } }),
  adminReport: (key: string, report_id: string, download: boolean) =>
    fetchBlob(`/admin/reports/${report_id}?download=${download}`, { headers: { 'X-Admin-Key': key } }),
  adminNotify: (key: string, survey_id: string) =>
    req<{ sent: boolean; to?: string; reason?: string }>(`/admin/surveys/${survey_id}/notify`, {
      method: 'POST',
      headers: { 'X-Admin-Key': key },
    }),
  adminAnalyze: (key: string, farm_id: string, survey_dir: string) =>
    req<{ survey_id: string; status: string }>('/admin/analyses', { headers: { 'X-Admin-Key': key }, body: { farm_id, survey_dir } }),
  adminSurveyStatus: (key: string, id: string) =>
    req<{ id: string; status: string; error: string | null }>(`/admin/surveys/${id}`, { headers: { 'X-Admin-Key': key } }),
  devSms: (mobile: string) => req<SmsMessage[]>(`/dev/sms?mobile=${encodeURIComponent(mobile)}`),
}

export function openBlob(blob: Blob, filename?: string) {
  const url = URL.createObjectURL(blob)
  if (filename) {
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
  } else {
    window.open(url, '_blank')
  }
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
}
