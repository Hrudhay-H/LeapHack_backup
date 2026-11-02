import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { Banner, Button, Card, Chip, Header, TextInput } from '../components/Ui'

type Overview = Awaited<ReturnType<typeof api.adminOverview>>

const DIRS = ['synthetic/stressed', 'synthetic/healthy', 'maize_rust']
const FARMS = ['FARM-001', 'FARM-002', 'FARM-003']

export default function Admin() {
  const [key, setKey] = useState('demo-admin')
  const [data, setData] = useState<Overview | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [farm, setFarm] = useState(FARMS[0])
  const [dir, setDir] = useState(DIRS[0])
  const [running, setRunning] = useState<string | null>(null)

  const load = useCallback(() => {
    api
      .adminOverview(key)
      .then((d) => {
        setData(d)
        setErr(null)
        // resume tracking an analysis that was started before this page (re)loaded
        const p = d.surveys.find((s) => s.status === 'PROCESSING')
        if (p) setRunning((r) => r ?? p.survey_id)
      })
      .catch((e) => setErr(e.message))
  }, [key])

  useEffect(load, [load])

  // Poll a running analysis until it finishes.
  useEffect(() => {
    if (!running) return
    const id = setInterval(async () => {
      try {
        const s = await api.adminSurveyStatus(key, running)
        if (s.status !== 'PROCESSING') {
          setRunning(null)
          setMsg(s.status === 'COMPLETED' ? `Analysis ${running} completed.` : `Analysis ${running} failed: ${s.error}`)
          load()
        }
      } catch (e) {
        setErr((e as Error).message)
        setRunning(null)
      }
    }, 2000)
    return () => clearInterval(id)
  }, [running, key, load])

  const notify = async (id: string) => {
    try {
      const r = await api.adminNotify(key, id)
      setMsg(r.sent ? `SMS queued to ${r.to}. Open the Demo phone to see it.` : `Not sent: ${r.reason}`)
    } catch (e) {
      setErr((e as Error).message)
    }
  }

  const analyze = async () => {
    setErr(null)
    try {
      const r = await api.adminAnalyze(key, farm, dir)
      setRunning(r.survey_id)
      setMsg(`Running pipeline for ${r.survey_id}…`)
      load()
    } catch (e) {
      setErr((e as Error).message)
    }
  }

  return (
    <div>
      <Header title="AgriScout AI" sub="FPO / admin overview" right={<Link to="/admin/simulate" className="rounded-lg bg-brand-600 px-3 py-2 text-sm font-medium text-white">Survey-day simulator</Link>} />
      <main className="mx-auto max-w-6xl space-y-4 px-4 py-5">
        <Card className="flex flex-wrap items-end gap-3">
          <div className="w-56">
            <TextInput label="Admin key (demo)" value={key} onChange={(e) => setKey(e.target.value)} />
          </div>
          <Button variant="secondary" onClick={load}>Refresh</Button>
        </Card>
        {err && <Banner tone="error">{err}</Banner>}
        {msg && <Banner tone="info">{msg}</Banner>}

        <Card className="space-y-3">
          <h2 className="font-semibold">Run a new analysis</h2>
          <p className="text-sm text-gray-600">Runs the full pipeline (alignment, crop mask, spectral baseline, PatchCore, fusion, hotspots) and generates the report.</p>
          <div className="flex flex-wrap items-end gap-3 text-sm">
            <label>
              <span className="mb-1 block font-medium text-gray-700">Farm</span>
              <select value={farm} onChange={(e) => setFarm(e.target.value)} className="rounded-lg border border-gray-300 px-3 py-2">
                {FARMS.map((f) => <option key={f}>{f}</option>)}
              </select>
            </label>
            <label>
              <span className="mb-1 block font-medium text-gray-700">Survey imagery</span>
              <select value={dir} onChange={(e) => setDir(e.target.value)} className="rounded-lg border border-gray-300 px-3 py-2">
                {DIRS.map((d) => <option key={d}>{d}</option>)}
              </select>
            </label>
            <Button onClick={analyze} disabled={!!running}>{running ? 'Running…' : 'Run analysis'}</Button>
          </div>
        </Card>

        <Card className="overflow-x-auto">
          <h2 className="mb-2 font-semibold">Surveys</h2>
          <table className="w-full text-left text-sm">
            <thead className="text-xs uppercase text-gray-500">
              <tr><th className="py-2">Survey</th><th>Farmer</th><th>Village</th><th>Status</th><th>Hotspots</th><th>Suspicious</th><th>Data</th><th /></tr>
            </thead>
            <tbody>
              {data?.surveys.map((s) => (
                <tr key={s.survey_id} className="border-t border-gray-100">
                  <td className="py-2 font-medium">{s.survey_id}</td>
                  <td>{s.farmer} <span className="text-gray-400">({s.farmer_id})</span></td>
                  <td>{s.village}</td>
                  <td><Chip color={s.status === 'COMPLETED' ? '#15803d' : s.status === 'FAILED' ? '#b91c1c' : '#b45309'}>{s.status}</Chip></td>
                  <td>{s.hotspots ?? '–'}</td>
                  <td>{s.suspicious_percent != null ? `${s.suspicious_percent}%` : '–'}</td>
                  <td className="text-xs text-gray-500">{s.data_source}</td>
                  <td className="text-right">
                    <Button variant="secondary" disabled={s.status !== 'COMPLETED'} onClick={() => notify(s.survey_id)} className="!px-2 !py-1 text-xs">
                      Send SMS
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>

        <Card className="overflow-x-auto">
          <h2 className="mb-2 font-semibold">Report access log</h2>
          <table className="w-full text-left text-sm">
            <thead className="text-xs uppercase text-gray-500">
              <tr><th className="py-2">When</th><th>Report</th><th>Who</th><th>Action</th><th>Authorization</th></tr>
            </thead>
            <tbody>
              {data?.access_log.length === 0 && <tr><td colSpan={5} className="py-3 text-gray-500">No access yet.</td></tr>}
              {data?.access_log.map((l, i) => (
                <tr key={i} className="border-t border-gray-100">
                  <td className="py-2">{new Date(l.at).toLocaleString()}</td>
                  <td>{l.report_id}</td>
                  <td>{l.actor_type} {l.actor_id}</td>
                  <td>{l.access_type}</td>
                  <td className="text-xs text-gray-500">{l.authorization_id}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </main>
    </div>
  )
}
