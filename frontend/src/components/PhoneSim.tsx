import { useEffect, useState } from 'react'
import { api } from '../api'
import type { SmsMessage } from '../types'

// Demo only: stands in for a real farmer's keypad phone. In production SMS goes through a gateway.
export const DEMO_PHONES = [
  { mobile: '9000000001', who: 'Ramesh Gowda · MDY-001' },
  { mobile: '9000000002', who: 'Lakshmamma · MDY-002 (keypad phone)' },
  { mobile: '9000000003', who: 'Suresh Kumar · MDY-003' },
]

export function PhoneSim() {
  const [open, setOpen] = useState(false)
  const [mobile, setMobile] = useState(DEMO_PHONES[1].mobile)
  const [msgs, setMsgs] = useState<SmsMessage[]>([])
  const [seen, setSeen] = useState<Record<string, number>>({})

  useEffect(() => {
    let alive = true
    const load = () =>
      api
        .devSms(mobile)
        .then((m) => alive && setMsgs(m))
        .catch(() => alive && setMsgs([]))
    load()
    const id = setInterval(load, 2000)
    return () => {
      alive = false
      clearInterval(id)
    }
  }, [mobile])

  useEffect(() => {
    if (open) setSeen((s) => ({ ...s, [mobile]: msgs.length }))
  }, [open, msgs.length, mobile])

  const unread = Math.max(msgs.length - (seen[mobile] ?? 0), 0)

  return (
    <div className="fixed bottom-4 right-4 z-[1000]">
      {open && (
        <div className="mb-3 w-72 rounded-[2rem] border-4 border-gray-800 bg-gray-900 p-3 shadow-2xl">
          <div className="mb-2 flex items-center justify-between text-[11px] text-gray-300">
            <span>DEMO PHONE</span>
            <button onClick={() => setOpen(false)} className="text-gray-400 hover:text-white" aria-label="Close phone">
              ✕
            </button>
          </div>
          <select
            value={mobile}
            onChange={(e) => setMobile(e.target.value)}
            className="mb-2 w-full rounded bg-gray-800 px-2 py-1 text-xs text-gray-100"
          >
            {DEMO_PHONES.map((p) => (
              <option key={p.mobile} value={p.mobile}>
                {p.who}
              </option>
            ))}
          </select>
          <div className="h-80 space-y-2 overflow-y-auto rounded-lg bg-[#c8e6b5] p-2 text-[13px] text-gray-900">
            {msgs.length === 0 && <div className="pt-8 text-center text-gray-600">No messages</div>}
            {msgs.map((m) => (
              <div key={m.pk} className="rounded bg-white/80 p-2 shadow-sm">
                <div className="mb-1 flex justify-between text-[10px] text-gray-500">
                  <span>AGRISCT</span>
                  <span>{new Date(m.at).toLocaleTimeString()}</span>
                </div>
                <div className={m.kind === 'OTP' ? 'font-medium' : ''}>{m.body}</div>
              </div>
            ))}
          </div>
          <div className="mt-2 grid grid-cols-3 gap-1 text-center text-xs text-gray-500">
            {'123456789*0#'.split('').map((k) => (
              <div key={k} className="rounded bg-gray-800 py-1">
                {k}
              </div>
            ))}
          </div>
        </div>
      )}
      <button
        onClick={() => setOpen((o) => !o)}
        className="relative ml-auto flex items-center gap-2 rounded-full bg-gray-900 px-4 py-2 text-sm font-medium text-white shadow-lg"
      >
        📱 Demo phone
        {unread > 0 && (
          <span className="absolute -right-1 -top-1 grid h-5 w-5 place-items-center rounded-full bg-red-600 text-[11px]">
            {unread}
          </span>
        )}
      </button>
    </div>
  )
}
