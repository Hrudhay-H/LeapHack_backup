import { Link } from 'react-router-dom'
import { Banner, Card, Header } from '../components/Ui'

const ENTRIES = [
  { to: '/farmer', icon: '📱', title: 'Farmer portal', text: 'Smartphone farmers sign in with an OTP, see their field map, hotspots and report.' },
  { to: '/operator', icon: '🏪', title: 'Operator portal', text: 'Village service centre helps keypad-phone farmers get their report, with the farmer’s OTP consent.' },
  { to: '/admin', icon: '📊', title: 'FPO overview', text: 'Run analyses, send SMS notifications and review who accessed which report.' },
]

export default function Landing() {
  return (
    <div>
      <Header title="AgriScout AI" sub="UAV crop-anomaly hotspots for early scouting" />
      <main className="mx-auto max-w-4xl space-y-6 px-4 py-8">
        <div>
          <h1 className="text-2xl font-semibold">From drone survey to a scouting plan</h1>
          <p className="mt-1 max-w-2xl text-gray-600">
            AgriScout finds where a crop field looks unusual, ranks the areas to inspect first, and delivers the result to every farmer, with or
            without a smartphone. It does not diagnose pests: hotspots need ground inspection.
          </p>
        </div>
        <div className="grid gap-4 md:grid-cols-3">
          {ENTRIES.map((e) => (
            <Link key={e.to} to={e.to}>
              <Card className="h-full transition-shadow hover:shadow-md">
                <div className="text-3xl">{e.icon}</div>
                <div className="mt-2 font-semibold">{e.title}</div>
                <p className="mt-1 text-sm text-gray-600">{e.text}</p>
              </Card>
            </Link>
          ))}
        </div>
        <Card className="text-sm">
          <div className="mb-2 font-semibold">Demo credentials (fictional data)</div>
          <ul className="space-y-1 text-gray-700">
            <li>Farmer with hotspots: <b>MDY-001</b> (OTP appears on the Demo phone, bottom right)</li>
            <li>Keypad-phone farmer, clean field: <b>MDY-002</b> (use the Operator portal)</li>
            <li>Operators: <b>OP-KIK</b> or <b>OP-MAD</b>, PIN <b>1234</b></li>
          </ul>
        </Card>
        <Banner tone="warn">
          The sample fields are <b>synthetic</b> (generated with known planted stress patches) to demonstrate the pipeline. They are not real survey
          results and say nothing about real-world pest-detection accuracy.
        </Banner>
      </main>
    </div>
  )
}
