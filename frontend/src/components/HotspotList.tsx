import { useLang } from '../lang'
import type { Key } from '../i18n'
import type { Hotspot, Verdict } from '../types'
import { Button, Chip, priorityColor } from './Ui'

const SIGNAL_TEXT: Record<Hotspot['dominant_signal'], string> = {
  BOTH: 'Image and vegetation analyses agree',
  RGB: 'Unusual canopy texture (experimental image check only)',
  MULTISPECTRAL: 'Unusual vegetation response (spectral only)',
  RGB_INDEX: 'Unusual greenness (colour index only)',
}

const CONF_COLOR = { HIGH: '#15803d', MEDIUM: '#b45309', LOW: '#6b7280' }

interface Props {
  hotspots: Hotspot[]
  selected: string | null
  onSelect: (id: string) => void
  onVerdict?: (h: Hotspot, v: Exclude<Verdict, null>) => void
  busy?: string | null
}

function Bar({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex items-center gap-2 text-[11px] text-gray-500">
      <span className="w-14">{label}</span>
      <div className="h-1.5 flex-1 overflow-hidden rounded bg-gray-100">
        <div className="h-full bg-brand-600" style={{ width: `${Math.round(Math.min(value, 1) * 100)}%` }} />
      </div>
    </div>
  )
}

export function HotspotList({ hotspots, selected, onSelect, onVerdict, busy }: Props) {
  const { t } = useLang()
  const verdictLabel = (v: Verdict): string =>
    v === 'PEST' ? t('pest') : v === 'NOT_PEST' ? t('notPest') : v === 'OTHER' ? t('other') : t('pending')

  return (
    <ul className="space-y-3">
      {hotspots.map((h, i) => (
        <li
          key={h.id}
          onClick={() => onSelect(h.id)}
          className={`cursor-pointer rounded-xl border p-3 transition-colors ${
            selected === h.id ? 'border-brand-600 bg-brand-50' : 'border-gray-200 bg-white hover:border-gray-300'
          }`}
        >
          <div className="flex flex-wrap items-center gap-2">
            <span className="grid h-6 w-6 place-items-center rounded-full bg-gray-900 text-xs font-semibold text-white">{i + 1}</span>
            <span className="text-sm font-semibold">{h.id}</span>
            <Chip color={priorityColor(h.priority)}>{t(`P_${h.priority}` as Key)}</Chip>
            <Chip color={CONF_COLOR[h.confidence]}>
              {t('confidence')}: {t(`C_${h.confidence}` as Key)}
            </Chip>
          </div>
          <div className="mt-2 text-sm text-gray-800">{h.pattern_hint}</div>
          <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-gray-600">
            <div>
              Area: <b>{h.estimated_area_sqm.toFixed(0)} m²</b> ({h.crop_area_percent}% of crop)
            </div>
            <div>
              Anomaly score: <b>{h.anomaly_score.toFixed(2)}</b>
            </div>
          </div>
          <div className="mt-2 space-y-1">
            <Bar label="Texture" value={h.rgb_signal} />
            <Bar label="Colour/veg." value={h.spectral_signal} />
          </div>
          <div className="mt-1 text-xs text-gray-500">{SIGNAL_TEXT[h.dominant_signal]}</div>

          <div className="mt-3 border-t border-gray-100 pt-2">
            <div className="mb-1 text-xs font-medium text-gray-500">
              {t('groundCheck')}: <span className="text-gray-900">{verdictLabel(h.verdict)}</span>
            </div>
            {onVerdict && (
              <div className="flex flex-wrap gap-2" onClick={(e) => e.stopPropagation()}>
                {(['PEST', 'NOT_PEST', 'OTHER'] as const).map((v) => (
                  <Button
                    key={v}
                    variant={h.verdict === v ? 'primary' : 'secondary'}
                    disabled={busy === h.id}
                    onClick={() => onVerdict(h, v)}
                    className="!px-2.5 !py-1 text-xs"
                  >
                    {verdictLabel(v)}
                  </Button>
                ))}
              </div>
            )}
          </div>
        </li>
      ))}
    </ul>
  )
}
