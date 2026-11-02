import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { FieldMap, LAYER_OPTIONS } from '../components/FieldMap'
import { HotspotList } from '../components/HotspotList'
import { Banner, Button, Card, Header, Stat } from '../components/Ui'
import { LangToggle, useLang } from '../lang'
import { savePdf, viewPdf } from '../pdf'
import type { FarmerMe, Hotspot, SurveyDetail, Verdict } from '../types'
import { FARMER_TOKEN } from './FarmerLogin'

const LAYER_KEYS = ['rgb', 'ndvi', 'ndre', 'spectral_anomaly', 'spectral_z', 'rgb_anomaly', 'fused_anomaly']

export default function FarmerDashboard() {
  const nav = useNavigate()
  const { t, setLang } = useLang()
  const token = sessionStorage.getItem(FARMER_TOKEN)

  const [me, setMe] = useState<FarmerMe | null>(null)
  const [surveyId, setSurveyId] = useState<string | null>(null)
  const [survey, setSurvey] = useState<SurveyDetail | null>(null)
  const [images, setImages] = useState<Record<string, string>>({})
  const [active, setActive] = useState('fused_anomaly')
  const [selected, setSelected] = useState<string | null>(null)
  const [outlines, setOutlines] = useState(true)
  const [context, setContext] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const logout = useCallback(() => {
    sessionStorage.removeItem(FARMER_TOKEN)
    nav('/farmer')
  }, [nav])

  useEffect(() => {
    if (!token) {
      nav('/farmer')
      return
    }
    api
      .farmerMe(token)
      .then((m) => {
        setMe(m)
        setLang(m.language)
        const newest = m.farms
          .flatMap((f) => f.surveys)
          .filter((s) => s.status === 'COMPLETED')
          .sort((a, b) => b.created_at.localeCompare(a.created_at))[0]
        if (newest) setSurveyId(newest.id)
      })
      .catch(logout)
  }, [token, nav, logout, setLang])

  useEffect(() => {
    if (!token || !surveyId) return
    let alive = true
    const urls: string[] = []
    api
      .farmerSurvey(token, surveyId)
      .then(async (s) => {
        if (!alive) return
        setSurvey(s)
        // Only request layers this survey actually has (RGB-only runs have no NDVI/NDRE; older runs lack newer layers).
        const keys = LAYER_KEYS.filter((k) => s.layers?.includes(k))
        const res = await Promise.allSettled(keys.map((k) => api.farmerLayer(token, surveyId, k)))
        if (!alive) return
        const out: Record<string, string> = {}
        res.forEach((r, i) => {
          if (r.status === 'fulfilled') {
            const u = URL.createObjectURL(r.value)
            urls.push(u)
            out[keys[i]] = u
          }
        })
        setImages(out)
      })
      .catch((e) => setErr((e as Error).message))
    return () => {
      alive = false
      urls.forEach(URL.revokeObjectURL)
    }
  }, [token, surveyId])

  const onVerdict = async (h: Hotspot, v: Exclude<Verdict, null>) => {
    if (!token || !survey) return
    setBusy(h.id)
    try {
      const upd = await api.verdict(token, survey.id, h.id, v)
      setSurvey({ ...survey, hotspots: survey.hotspots.map((x) => (x.id === h.id ? { ...x, ...upd } : x)) })
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  if (!token) return null
  const sm = survey?.summary
  const clear = sm?.status === 'no_significant_anomaly'
  const completed = (me?.farms ?? [])
    .flatMap((f) => f.surveys.map((s) => ({ ...s, farm: f.name })))
    .filter((s) => s.status === 'COMPLETED')
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
  const layerOptions = LAYER_OPTIONS.filter((o) => o.key === 'none' || images[o.key])

  return (
    <div>
      <Header
        title="AgriScout AI"
        sub={me ? `${me.name} · ${me.village}` : 'Farmer portal'}
        right={
          <>
            <LangToggle />
            <Button variant="secondary" onClick={logout}>
              {t('logout')}
            </Button>
          </>
        }
      />
      <main className="mx-auto max-w-6xl space-y-4 px-4 py-5">
        {survey?.data_source === 'synthetic_demo' && (
          <Banner tone="error">
            <b>Demo data.</b> This field is synthetic (generated for testing), not a real survey.
          </Banner>
        )}
        {survey?.dataset && survey.data_source !== 'synthetic_demo' && (
          <Banner tone={survey.dataset.simulated_stress ? 'warn' : 'info'}>
            <b>{survey.dataset.simulated_stress ? 'Real imagery with simulated stress.' : 'Real UAV imagery from a public research dataset'}</b> (
            {survey.dataset.crop}, {survey.dataset.license}). {survey.dataset.attribution}.{' '}
            {survey.dataset.simulated_stress ??
              'Shown to demonstrate the pipeline; this field has no ground-verified pest or disease records.'}
          </Banner>
        )}
        {err && <Banner tone="error">{err}</Banner>}
        {!me && <div className="py-10 text-center text-gray-500">Loading…</div>}
        {me && !surveyId && <Banner tone="info">No completed surveys yet.</Banner>}

        {survey && sm && (
          <>
            {completed.length > 1 && (
              <label className="flex flex-wrap items-center gap-2 text-sm text-gray-700">
                <span className="font-medium">Survey</span>
                <select
                  value={surveyId ?? ''}
                  onChange={(e) => {
                    setSurveyId(e.target.value)
                    setSurvey(null)
                    setImages({})
                    setSelected(null)
                  }}
                  className="rounded-lg border border-gray-300 bg-white px-3 py-1.5"
                >
                  {completed.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.farm} · {new Date(s.created_at).toLocaleString()}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h1 className="text-xl font-semibold">
                  {t('hello')}, {me?.name}
                </h1>
                <div className="text-sm text-gray-500">
                  {survey.farm.name} · {survey.farm.crop} · survey {new Date(survey.created_at).toLocaleDateString()}
                </div>
              </div>
              <div className="flex gap-2">
                <Button variant="secondary" onClick={() => viewPdf(() => api.farmerReport(token, survey.id, false)).catch((e) => setErr(e.message))}>
                  {t('viewReport')}
                </Button>
                <Button onClick={() => savePdf(() => api.farmerReport(token, survey.id, true), `${survey.report_id}.pdf`).catch((e) => setErr(e.message))}>
                  {t('downloadReport')}
                </Button>
              </div>
            </div>

            {clear ? (
              <Banner tone="ok">
                <b>{t('noAnomaly')}.</b> {t('noAnomalyHelp')}
              </Banner>
            ) : (
              <Banner tone="warn">{t('disclaimer')}</Banner>
            )}

            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <Stat label={t('cropAnalysed')} value={`${Math.round(sm.valid_crop_area_sqm)} m²`} />
              <Stat label={t('areasToInspect')} value={sm.hotspots_detected} />
              <Stat label={t('suspiciousArea')} value={`${Math.round(sm.suspicious_area_sqm)} m²`} />
              <Stat label={t('shareOfCrop')} value={`${sm.suspicious_area_percent}%`} />
            </div>

            <div className="grid gap-4 lg:grid-cols-3">
              <div className="space-y-3 lg:col-span-2">
                <Card className="!p-2">
                  {images.rgb ? (
                    <FieldMap
                      bounds={survey.image.bounds_wgs84}
                      images={images}
                      active={active}
                      hotspots={survey.hotspots}
                      selected={selected}
                      onSelect={setSelected}
                      outlines={outlines}
                      context={context}
                    />
                  ) : (
                    <div className="grid h-[420px] place-items-center text-gray-500">Loading map…</div>
                  )}
                </Card>
                <Card>
                  <div className="mb-2 text-sm font-medium text-gray-700">{t('layers')}</div>
                  <div className="flex flex-wrap gap-x-4 gap-y-2 text-sm">
                    {layerOptions.map((o) => (
                      <label key={o.key} className="flex items-center gap-1.5">
                        <input type="radio" name="layer" checked={active === o.key} onChange={() => setActive(o.key)} />
                        {o.label}
                      </label>
                    ))}
                  </div>
                  <div className="mt-3 flex gap-4 text-sm text-gray-600">
                    <label className="flex items-center gap-1.5">
                      <input type="checkbox" checked={outlines} onChange={(e) => setOutlines(e.target.checked)} /> Hotspot outlines
                    </label>
                    <label className="flex items-center gap-1.5">
                      <input type="checkbox" checked={context} onChange={(e) => setContext(e.target.checked)} /> Street map underneath
                    </label>
                  </div>
                  {active === 'spectral_z' && (
                    <p className="mt-3 rounded-lg bg-gray-50 p-2 text-xs text-gray-600">
                      Shows how far each area is from this field's typical vegetation reading. Values below the alert level are shown for context
                      only and are <b>not</b> alerts. Row structure, shadows and soil show up here too.
                    </p>
                  )}
                  <p className="mt-3 text-xs text-gray-500">
                    The vegetation-index baseline is the main signal; the visual texture check is experimental. Where both light up, evidence is stronger. Where only one does, the
                    cause may be different.
                  </p>
                </Card>
              </div>

              <div>
                <h2 className="mb-2 text-base font-semibold">
                  {t('hotspots')} ({survey.hotspots.length})
                </h2>
                {survey.hotspots.length === 0 ? (
                  <Card className="text-sm text-gray-600">{t('noAnomaly')}</Card>
                ) : (
                  <HotspotList hotspots={survey.hotspots} selected={selected} onSelect={setSelected} onVerdict={onVerdict} busy={busy} />
                )}
              </div>
            </div>

            {survey.synthetic_check && (
              <Card className="text-sm">
                <div className="font-semibold">Pipeline self-check (planted patches only)</div>
                <p className="mt-1 text-gray-600">{survey.synthetic_check.note}</p>
                <div className="mt-2 text-gray-700">
                  Planted patches found: <b>{survey.synthetic_check.patches.filter((p) => p.detected).length}</b> of{' '}
                  {survey.synthetic_check.patches.length} · pixel recall {survey.synthetic_check.pixel_recall} · precision{' '}
                  {survey.synthetic_check.pixel_precision}
                </div>
              </Card>
            )}
          </>
        )}
      </main>
    </div>
  )
}
