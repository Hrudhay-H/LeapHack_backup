import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { Banner, Button, Card, Chip, Header, Stat, TextInput } from '../components/Ui'
import { savePdf, viewPdf } from '../pdf'
import type { SimFarm, SimStatus } from '../types'

const ACCESS_TEXT: Record<string, string> = {
  DIGITAL: 'Smartphone: dashboard and PDF',
  ASSISTED: 'Keypad phone: SMS, then collects the report through an operator',
  BOTH: 'Smartphone and operator access',
}

function StageList({ stages, farm }: { stages: SimStatus['stages']; farm: SimFarm }) {
  const cur = stages.findIndex((s) => s.key === farm.stage)
  const done = farm.stage === 'done'
  return (
    <ol className="space-y-1.5 text-sm">
      {stages.map((s, i) => {
        const state = farm.status === 'NOT_STARTED' ? 'pending' : done || i < cur ? 'done' : i === cur ? 'active' : 'pending'
        return (
          <li key={s.key} className="flex items-center gap-2">
            <span
              className={`grid h-5 w-5 place-items-center rounded-full text-[11px] ${
                state === 'done' ? 'bg-brand-600 text-white' : state === 'active' ? 'animate-pulse bg-amber-400 text-white' : 'bg-gray-200 text-gray-400'
              }`}
            >
              {state === 'done' ? '✓' : i + 1}
            </span>
            <span className={state === 'pending' ? 'text-gray-400' : state === 'active' ? 'font-medium text-gray-900' : 'text-gray-700'}>
              {s.label}
            </span>
          </li>
        )
      })}
    </ol>
  )
}

function FarmCard({ farm, stages, adminKey, thumb, onError }: { farm: SimFarm; stages: SimStatus['stages']; adminKey: string; thumb?: string; onError: (m: string) => void }) {
  const r = farm.result
  const stress = farm.input.simulated_stress
  return (
    <Card className="flex flex-col gap-3">
      <div>
        <div className="text-xs font-medium uppercase tracking-wide text-gray-500">{farm.farm_id}</div>
        <div className="text-lg font-semibold">{farm.farm_name}</div>
        <div className="text-sm text-gray-600">
          {farm.farmer} ({farm.farmer_id}) · {farm.village}
        </div>
        <div className="mt-1 text-xs text-gray-500">{farm.access_mode ? ACCESS_TEXT[farm.access_mode] : ''}</div>
      </div>

      <div className="rounded-lg bg-gray-50 p-2 text-xs text-gray-600">
        <div className="mb-1 flex items-center gap-2">
          <b className="text-gray-800">Simulated input</b>
          <Chip color={stress ? '#b45309' : '#15803d'}>{stress ? `${farm.input.planted_patches.length} stress patches added` : 'Real imagery, untouched'}</Chip>
        </div>
        {farm.input.source}.
        {stress && (
          <ul className="mt-1 list-disc pl-4">
            {farm.input.planted_patches.map((p, i) => (
              <li key={i}>
                {p.name}: ~{p.radius_m} m, severity {p.severity}
              </li>
            ))}
          </ul>
        )}
      </div>

      <StageList stages={stages} farm={farm} />
      {farm.status === 'FAILED' && <Banner tone="error">Analysis failed: {farm.error?.split('\n')[0]}</Banner>}

      {r && (
        <div className="space-y-3 border-t border-gray-100 pt-3">
          {r.hotspots === 0 ? (
            <Banner tone="ok">
              <b>No significant anomaly detected.</b> A valid result, not a failed scan.
            </Banner>
          ) : (
            <Banner tone="warn">
              <b>{r.hotspots} hotspot(s)</b> flagged for ground inspection.
            </Banner>
          )}
          <div className="grid grid-cols-3 gap-2">
            <Stat label="Hotspots" value={r.hotspots ?? '–'} />
            <Stat label="Suspicious" value={`${r.suspicious_percent ?? 0}%`} />
            <Stat label="Crop area" value={`${Math.round(r.valid_crop_area_sqm ?? 0)} m²`} />
          </div>
          {thumb && <img src={thumb} alt={`Hotspot overlay for ${farm.farm_name}`} className="w-full rounded-lg border border-gray-200" />}
          {stress && r.patches_total != null && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-2 text-xs text-amber-900">
              <b>Self-check against the added patches:</b> {r.patches_found} of {r.patches_total} patches found · every flagged pixel inside a planted
              patch {r.pixel_precision != null ? `(precision ${r.pixel_precision})` : ''} · share of planted area covered {r.pixel_recall ?? '–'}. Mild
              or small patches can be missed; this tests the pipeline, not real pest detection.
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            {r.report_id && (
              <>
                <Button variant="secondary" onClick={() => viewPdf(() => api.adminReport(adminKey, r.report_id!, false)).catch((e) => onError(e.message))}>
                  Open PDF report
                </Button>
                <Button variant="secondary" onClick={() => savePdf(() => api.adminReport(adminKey, r.report_id!, true), `${r.report_id}.pdf`).catch((e) => onError(e.message))}>
                  Download
                </Button>
              </>
            )}
          </div>
          {r.sms && (
            <div className="text-xs">
              <div className="mb-1 font-medium text-gray-700">SMS sent to {farm.farmer} (mock gateway)</div>
              <div className="rounded-lg bg-[#c8e6b5] p-2 text-[13px] text-gray-900">{r.sms}</div>
            </div>
          )}
          <div className="text-xs text-gray-500">
            {farm.access_mode === 'ASSISTED' ? (
              <>
                Collect via the <Link to="/operator" className="text-brand-700 underline">operator portal</Link> (Farmer ID {farm.farmer_id}).
              </>
            ) : (
              <>
                Farmer view: <Link to="/farmer" className="text-brand-700 underline">sign in</Link> as {farm.farmer_id}. The new survey is shown first.
              </>
            )}
          </div>
        </div>
      )}
    </Card>
  )
}

export default function Simulate() {
  const [key, setKey] = useState('demo-admin')
  const [st, setSt] = useState<SimStatus | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [thumbs, setThumbs] = useState<Record<string, string>>({})
  const fetched = useRef<Set<string>>(new Set())

  const load = useCallback(() => {
    api
      .adminSimStatus(key)
      .then((s) => {
        setSt(s)
        setErr(null)
      })
      .catch((e) => setErr(e.message))
  }, [key])

  useEffect(load, [load])
  useEffect(() => {
    if (!st?.started || st.finished) return
    const id = setInterval(load, 1500)
    return () => clearInterval(id)
  }, [st?.started, st?.finished, load])

  // overlay thumbnails once each farm completes
  useEffect(() => {
    st?.farms.forEach((f) => {
      if (f.status === 'COMPLETED' && f.survey_id && !fetched.current.has(f.survey_id)) {
        fetched.current.add(f.survey_id)
        api
          .adminLayer(key, f.survey_id, 'overlay')
          .then((b) => setThumbs((t) => ({ ...t, [f.survey_id!]: URL.createObjectURL(b) })))
          .catch(() => undefined)
      }
    })
  }, [st, key])

  const start = async () => {
    setBusy(true)
    setErr(null)
    try {
      await api.adminSimStart(key)
      load()
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const reset = async () => {
    setBusy(true)
    try {
      await api.adminSimReset(key)
      fetched.current.clear()
      setThumbs({})
      load()
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const running = !!st?.started && !st.finished
  return (
    <div>
      <Header title="AgriScout AI" sub="Survey-day simulator" right={<Link to="/admin" className="text-sm text-gray-600 underline">Back to admin</Link>} />
      <main className="mx-auto max-w-6xl space-y-4 px-4 py-5">
        <Card className="space-y-2 text-sm text-gray-700">
          <h1 className="text-lg font-semibold text-gray-900">Simulate a survey day for three farms</h1>
          <p>
            Each farm receives a new drone survey. The imagery is <b>real</b> (a rice research station from a public UAV dataset, CC BY 4.0). Farm 1 is
            left untouched. Farms 2 and 3 have <b>simulated stress patches blended into the real imagery</b>, at known locations, so we can check what the
            pipeline finds and misses. The patches are <b>not real pest or disease damage</b>, and the reports say so.
          </p>
          <p className="text-gray-500">
            Then the real pipeline runs: quality checks, vegetation-index analysis, the experimental visual check, hotspot extraction, a PDF report, and an
            SMS to the farmer. The new survey appears first on each farmer's dashboard.
          </p>
        </Card>

        {st && !st.ready && (
          <Banner tone="warn">
            Simulation imagery is not prepared ({st.missing.join(', ')}). Run once: <code className="rounded bg-white/60 px-1">{st.prepare_command}</code>
          </Banner>
        )}
        {err && <Banner tone="error">{err}</Banner>}

        <Card className="flex flex-wrap items-end gap-3">
          <div className="w-48">
            <TextInput label="Admin key (demo)" value={key} onChange={(e) => setKey(e.target.value)} />
          </div>
          <Button onClick={start} disabled={busy || running || !st?.ready || !!st?.started}>
            {running ? 'Survey running…' : 'Start survey day'}
          </Button>
          <Button variant="secondary" onClick={reset} disabled={busy || running || !st?.started}>
            Reset simulation
          </Button>
          {st?.finished && <span className="text-sm text-gray-600">Done. Open the reports below, or sign in as a farmer to see the new survey.</span>}
        </Card>

        <div className="grid gap-4 lg:grid-cols-3">
          {st?.farms.map((f) => (
            <FarmCard key={f.farm_id} farm={f} stages={st.stages} adminKey={key} thumb={f.survey_id ? thumbs[f.survey_id] : undefined} onError={setErr} />
          ))}
        </div>
      </main>
    </div>
  )
}
