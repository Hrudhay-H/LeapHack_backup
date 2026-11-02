import type { Geometry } from 'geojson'

export type Priority = 'CRITICAL' | 'HIGH' | 'MODERATE' | 'LOW'
export type Confidence = 'HIGH' | 'MEDIUM' | 'LOW'
export type Verdict = 'PEST' | 'NOT_PEST' | 'OTHER' | null

export interface Hotspot {
  id: string
  anomaly_score: number
  peak_score: number
  estimated_area_sqm: number
  crop_area_percent: number
  priority: Priority
  confidence: Confidence
  agreement: number
  dominant_signal: 'BOTH' | 'RGB' | 'MULTISPECTRAL' | 'RGB_INDEX'
  rgb_signal: number
  spectral_signal: number
  pattern: string
  pattern_hint: string
  centroid: [number, number]
  geometry: Geometry
  verdict: Verdict
  verdict_note: string
  verdict_by: string
  verdict_at: string | null
}

export interface SurveySummary {
  valid_crop_area_sqm: number
  suspicious_area_sqm: number
  suspicious_area_percent: number
  hotspots_detected: number
  status: 'anomalies_detected' | 'no_significant_anomaly'
}

export interface SurveyDetail {
  id: string
  farm: { id: string; name: string; crop: string }
  status: string
  created_at: string
  data_source: string
  summary: SurveySummary
  image: { width_px: number; height_px: number; gsd_m: number; bounds_wgs84: [number, number, number, number] }
  branches: {
    spectral: { max_unit: number; area_flagged_pct: number }
    rgb_patchcore: { max_unit: number; area_flagged_pct: number } | null
  }
  quality: { quality_ok: boolean }
  model_version: string
  warning: string
  layers?: string[]
  dataset?: { crop?: string; source?: string; doi?: string; license?: string; attribution?: string; site?: string; simulated_stress?: string } | null
  synthetic_check?: {
    note: string
    pixel_iou: number
    pixel_recall: number
    pixel_precision: number
    patches: { area_sqm: number; coverage: number; detected: boolean }[]
  }
  hotspots: Hotspot[]
  report_id: string | null
}

export interface FarmerMe {
  id: string
  name: string
  village: string
  language: 'kn' | 'en'
  farms: {
    id: string
    name: string
    crop: string
    surveys: { id: string; status: string; created_at: string; summary: SurveySummary | null; data_source: string }[]
  }[]
}

export interface SmsMessage {
  pk: number
  to_mobile: string
  body: string
  kind: string
  at: string
}

export interface SimFarm {
  farm_id: string
  farm_name: string
  farmer_id: string
  farmer: string | null
  village: string | null
  language: 'kn' | 'en' | null
  access_mode: 'DIGITAL' | 'ASSISTED' | 'BOTH' | null
  input: {
    source: string
    simulated_stress: boolean
    planted_patches: { name: string | null; radius_m: number | null; severity: number | null }[]
  }
  survey_id: string | null
  status: 'NOT_STARTED' | 'PROCESSING' | 'COMPLETED' | 'FAILED'
  stage: string
  error: string | null
  result: {
    hotspots: number | null
    suspicious_percent: number | null
    valid_crop_area_sqm: number | null
    status: string | null
    patches_found: number | null
    patches_total: number | null
    pixel_recall: number | null
    pixel_precision: number | null
    report_id: string | null
    notified: boolean
    sms: string | null
  } | null
}

export interface SimStatus {
  stages: { key: string; label: string }[]
  farms: SimFarm[]
  started: boolean
  finished: boolean
  ready: boolean
  missing: string[]
  prepare_command: string
}
