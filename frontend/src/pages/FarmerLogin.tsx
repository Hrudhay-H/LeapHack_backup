import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { Banner, Button, Card, Header, TextInput } from '../components/Ui'

export const FARMER_TOKEN = 'agri.farmer.token'

export default function FarmerLogin() {
  const nav = useNavigate()
  const [farmerId, setFarmerId] = useState('MDY-001')
  const [challenge, setChallenge] = useState<string | null>(null)
  const [otp, setOtp] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const requestCode = async () => {
    setBusy(true)
    setErr(null)
    try {
      const r = await api.farmerRequestOtp(farmerId.trim())
      setChallenge(r.challenge_id)
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const verify = async () => {
    if (!challenge) return
    setBusy(true)
    setErr(null)
    try {
      const r = await api.farmerVerify(challenge, otp)
      sessionStorage.setItem(FARMER_TOKEN, r.token)
      nav('/farmer/dashboard')
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <Header title="AgriScout AI" sub="Farmer portal" />
      <main className="mx-auto max-w-md px-4 py-10">
        <Card className="space-y-4">
          <h1 className="text-xl font-semibold">Sign in</h1>
          <TextInput label="Farmer ID" value={farmerId} onChange={(e) => setFarmerId(e.target.value)} disabled={!!challenge} />
          {!challenge ? (
            <Button onClick={requestCode} disabled={busy || !farmerId.trim()} className="w-full">
              Send code to my phone
            </Button>
          ) : (
            <>
              <Banner tone="info">
                A 6-digit code was sent to the phone registered for this ID. It expires in 5 minutes. In this demo, open the
                <b> Demo phone</b> at the bottom right to read it.
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
                <Button onClick={verify} disabled={busy || otp.length !== 6} className="flex-1">
                  Verify and continue
                </Button>
                <Button variant="secondary" onClick={() => { setChallenge(null); setOtp('') }}>
                  Back
                </Button>
              </div>
            </>
          )}
          {err && <Banner tone="error">{err}</Banner>}
        </Card>
      </main>
    </div>
  )
}
