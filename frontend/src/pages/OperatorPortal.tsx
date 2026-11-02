import { useEffect, useState } from 'react'
import { api, ApiError } from '../api'
import { HotspotList } from '../components/HotspotList'
import { Banner, Button, Card, Header, Stat, TextInput } from '../components/Ui'
import { explain } from '../explain'
import type { Lang } from '../i18n'
import { LangProvider, useLang } from '../lang'
import { savePdf, viewPdf } from '../pdf'
import type { Hotspot, SurveyDetail, Verdict } from '../types'

const OP_KEY = 'agri.operator'

type Op = { token: string; operator: { id: string; name: string; centre: string } }
type Found = Awaited<ReturnType<typeof api.lookup>>

const STEPS = ['Find farmer', 'Request consent code', "Farmer's code", 'Report']

function Stepper({ step }: { step: number }) {
  return (
    <ol className="flex flex-wrap gap-2 text-sm">
      {STEPS.map((s, i) => (
        <li
          key={s}
          className={`flex items-center gap-2 rounded-full px-3 py-1 ${
            i === step ? 'bg-brand-600 text-white' : i < step ? 'bg-brand-100 text-brand-900' : 'bg-gray-100 text-gray-500'
          }`}
        >
          <span className="font-semibold">{i + 1}</span> {s}
        </li>
      ))}
    </ol>
  )
}

function Portal() {
  const { t } = useLang()
  const [op, setOp] = useState<Op | null>(() => {
    try {
      return JSON.parse(sessionStorage.getItem(OP_KEY) ?? 'null')
    } catch {
      return null
    }
  })
  const [loginId, setLoginId] = useState('OP-MAD')
  const [pin, setPin] = useState('')
  const [farmerQ, setFarmerQ] = useState('MDY-002')
  const [found, setFound] = useState<Found | null>(null)
  const [reportId, setReportId] = useState<string | null>(null)
  const [reqId, setReqId] = useState<string | null>(null)
  const [otp, setOtp] = useState('')
  const [access, setAccess] = useState<{ token: string; expires: number } | null>(null)
  const [survey, setSurvey] = useState<SurveyDetail | null>(null)
  const [now, setNow] = useState(Date.now())
  const [lang, setLang] = useState<Lang>('kn')
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const step = survey && access ? 3 : reqId ? 2 : found ? 1 : 0
  const secondsLeft = access ? Math.max(Math.floor((access.expires - now) / 1000), 0) : 0

  useEffect(() => {
    if (!access) return
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [access])

  // Authorization is short-lived: drop the report from the screen when it lapses.
  useEffect(() => {
    if (access && secondsLeft === 0) {
      setAccess(null)
      setSurvey(null)
      setReqId(null)
      setOtp('')
      setErr('Authorization expired. Ask the farmer for a new code to open the report again.')
    }
  }, [access, secondsLeft])

  const run = async (label: string, fn: () => Promise<void>) => {
    setBusy(label)
    setErr(null)
    try {
      await fn()
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : (e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const reset = () => {
    setFound(null); setReportId(null); setReqId(null); setOtp(''); setAccess(null); setSurvey(null); setErr(null)
  }

  const login = () =>
    run('login', async () => {
      const r = await api.operatorLogin(loginId.trim(), pin)
      sessionStorage.setItem(OP_KEY, JSON.stringify(r))
      setOp(r)
    })

  const logout = () => {
    sessionStorage.removeItem(OP_KEY)
    setOp(null)
    reset()
  }

  const lookup = () =>
    run('lookup', async () => {
      const r = await api.lookup(op!.token, farmerQ.trim())
      setFound(r)
      setLang(r.language)
      setReportId(r.reports[0]?.report_id ?? null)
    })

  const requestCode = () =>
    run('request', async () => {
      const r = await api.createRequest(op!.token, found!.farmer_id, reportId!)
      setReqId(r.request_id)
    })

  const verify = () =>
    run('verify', async () => {
      const r = await api.verifyRequest(op!.token, reqId!, otp)
      setAccess({ token: r.access_token, expires: new Date(r.expires_at).getTime() })
      setNow(Date.now())
      setSurvey(await api.assistedSummary(op!.token, r.report_id, r.access_token))
      setOtp('')
    })

  const onVerdict = (h: Hotspot, v: Exclude<Verdict, null>) =>
    run(h.id, async () => {
      const upd = await api.verdict(op!.token, survey!.id, h.id, v, '', access!.token)
      setSurvey({ ...survey!, hotspots: survey!.hotspots.map((x) => (x.id === h.id ? { ...x, ...upd } : x)) })
    })

  if (!op) {
    return (
      <>
        <Header title="AgriScout AI" sub="Operator portal · assisted access" />
        <main className="mx-auto max-w-md px-4 py-10">
          <Card className="space-y-4">
            <h1 className="text-xl font-semibold">Operator sign in</h1>
            <TextInput label="Operator ID" value={loginId} onChange={(e) => setLoginId(e.target.value)} />
            <TextInput label="PIN" type="password" value={pin} onChange={(e) => setPin(e.target.value)} placeholder="Demo PIN: 1234" />
            <Button onClick={login} disabled={busy === 'login' || !pin} className="w-full">
              Sign in
            </Button>
            {err && <Banner tone="error">{err}</Banner>}
          </Card>
        </main>
      </>
    )
  }

  const mm = String(Math.floor(secondsLeft / 60)).padStart(1, '0')
  const ss = String(secondsLeft % 60).padStart(2, '0')

  return (
    <>
      <Header
        title="AgriScout AI"
        sub={`${op.operator.centre} · ${op.operator.name}`}
        right={
          <Button variant="secondary" onClick={logout}>
            {t('logout')}
          </Button>
        }
      />
      <main className="mx-auto max-w-4xl space-y-4 px-4 py-5">
        <Stepper step={step} />
        {err && <Banner tone="error">{err}</Banner>}

        {!survey && (
          <Card className="space-y-4">
            {!found && (
              <>
                <h2 className="text-lg font-semibold">Find the farmer</h2>
                <TextInput label="Farmer ID" value={farmerQ} onChange={(e) => setFarmerQ(e.target.value)} />
                <Button onClick={lookup} disabled={busy === 'lookup' || !farmerQ.trim()}>
                  Find farmer
                </Button>
              </>
            )}

            {found && !reqId && (
              <>
                <h2 className="text-lg font-semibold">Confirm this is the farmer in front of you</h2>
                <div className="rounded-lg bg-gray-50 p-3 text-sm">
                  <div className="text-base font-semibold">{found.name}</div>
                  <div className="text-gray-600">{found.village}</div>
                  <div className="text-gray-600">Registered phone: {found.masked_mobile}</div>
                </div>
                {found.reports.length === 0 ? (
                  <Banner tone="info">No reports are ready for this farmer.</Banner>
                ) : (
                  <label className="block text-sm">
                    <span className="mb-1 block font-medium text-gray-700">Report</span>
                    <select
                      value={reportId ?? ''}
                      onChange={(e) => setReportId(e.target.value)}
                      className="w-full rounded-lg border border-gray-300 px-3 py-2"
                    >
                      {found.reports.map((r) => (
                        <option key={r.report_id} value={r.report_id}>
                          {r.report_id} · {new Date(r.generated_at).toLocaleDateString()} · {r.hotspots_detected ?? '?'} area(s)
                        </option>
                      ))}
                    </select>
                  </label>
                )}
                <Banner tone="info">
                  A one-time code will be sent to the farmer's registered phone. The code only proves control of that phone, so also check the
                  farmer's identity as your centre's process requires.
                </Banner>
                <div className="flex gap-2">
                  <Button onClick={requestCode} disabled={!reportId || busy === 'request'}>
                    Send code to farmer's phone
                  </Button>
                  <Button variant="secondary" onClick={reset}>
                    Not this farmer
                  </Button>
                </div>
              </>
            )}

            {found && reqId && (
              <>
                <h2 className="text-lg font-semibold">Farmer enters the code</h2>
                <Banner tone="warn">
                  Let the <b>farmer</b> type or read out the 6-digit code sent to {found.masked_mobile}. Do not copy it down. It works once, for
                  5 minutes, and locks after 3 wrong tries.
                </Banner>
                <TextInput
                  label="6-digit code"
                  inputMode="numeric"
                  maxLength={6}
                  value={otp}
                  onChange={(e) => setOtp(e.target.value.replace(/\D/g, ''))}
                  autoFocus
                />
                <div className="flex gap-2">
                  <Button onClick={verify} disabled={otp.length !== 6 || busy === 'verify'}>
                    Authorize access
                  </Button>
                  <Button variant="secondary" onClick={reset}>
                    Cancel
                  </Button>
                </div>
              </>
            )}
          </Card>
        )}

        {survey && access && found && (
          <>
            <Banner tone="ok">
              Authorized by the farmer for <b>{found.name}</b> · {survey.report_id} only · access ends in{' '}
              <b>
                {mm}:{ss}
              </b>
              . Everything you do here is logged.
            </Banner>

            <div className="flex flex-wrap items-center gap-2">
              <Button onClick={() => savePdf(() => api.assistedDownload(op.token, survey.report_id!, access.token), `${survey.report_id}.pdf`).catch((e) => setErr(e.message))}>
                Download PDF
              </Button>
              <Button variant="secondary" onClick={() => viewPdf(() => api.assistedDownload(op.token, survey.report_id!, access.token)).catch((e) => setErr(e.message))}>
                Open to print
              </Button>
              <Button variant="secondary" onClick={reset}>
                Finish
              </Button>
            </div>

            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <Stat label={t('cropAnalysed')} value={`${Math.round(survey.summary.valid_crop_area_sqm)} m²`} />
              <Stat label={t('areasToInspect')} value={survey.summary.hotspots_detected} />
              <Stat label={t('suspiciousArea')} value={`${Math.round(survey.summary.suspicious_area_sqm)} m²`} />
              <Stat label={t('shareOfCrop')} value={`${survey.summary.suspicious_area_percent}%`} />
            </div>

            <Card>
              <div className="mb-2 flex items-center justify-between">
                <h3 className="font-semibold">Explain to the farmer</h3>
                <div className="inline-flex overflow-hidden rounded-full border border-gray-300 text-xs">
                  {(['kn', 'en'] as const).map((l) => (
                    <button key={l} onClick={() => setLang(l)} className={`px-3 py-1 ${lang === l ? 'bg-brand-600 text-white' : 'bg-white'}`}>
                      {l === 'kn' ? 'ಕನ್ನಡ' : 'English'}
                    </button>
                  ))}
                </div>
              </div>
              <p className="rounded-lg bg-gray-50 p-3 text-base leading-relaxed">{explain(lang, found.name, survey)}</p>
              <p className="mt-2 text-xs text-gray-500">Rule-based script generated from the report. Kannada wording needs review by a local expert.</p>
            </Card>

            {survey.hotspots.length > 0 && (
              <div>
                <h3 className="mb-2 font-semibold">{t('hotspots')}</h3>
                <HotspotList hotspots={survey.hotspots} selected={null} onSelect={() => {}} onVerdict={onVerdict} busy={busy} />
              </div>
            )}
          </>
        )}
      </main>
    </>
  )
}

export default function OperatorPortal() {
  return (
    <LangProvider>
      <Portal />
    </LangProvider>
  )
}
