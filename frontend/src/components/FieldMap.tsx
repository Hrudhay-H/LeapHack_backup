import { useEffect } from 'react'
import { GeoJSON, ImageOverlay, MapContainer, TileLayer, useMap } from 'react-leaflet'
import type { Feature } from 'geojson'
import type { LatLngBoundsExpression } from 'leaflet'
import type { Hotspot } from '../types'
import { priorityColor } from './Ui'

export const LAYER_OPTIONS = [
  { key: 'none', label: 'Field photo (RGB)' },
  { key: 'ndre', label: 'Vegetation vigour (NDRE)' },
  { key: 'ndvi', label: 'Vegetation cover (NDVI)' },
  { key: 'spectral_anomaly', label: 'Vegetation-index anomaly (baseline)' },
  { key: 'spectral_z', label: 'Deviation from field median (incl. below alert level)' },
  { key: 'rgb_anomaly', label: 'Visual texture anomaly (experimental)' },
  { key: 'fused_anomaly', label: 'Fused anomaly' },
] as const

function Fit({ bounds }: { bounds: LatLngBoundsExpression }) {
  const map = useMap()
  useEffect(() => {
    map.fitBounds(bounds, { padding: [10, 10] })
  }, [map, bounds])
  return null
}

interface Props {
  bounds: [number, number, number, number] // south, west, north, east
  images: Record<string, string> // layer key -> object URL
  active: string
  hotspots: Hotspot[]
  selected: string | null
  onSelect: (id: string) => void
  outlines: boolean
  context: boolean
}

export function FieldMap({ bounds, images, active, hotspots, selected, onSelect, outlines, context }: Props) {
  const [s, w, n, e] = bounds
  const b: LatLngBoundsExpression = [
    [s, w],
    [n, e],
  ]
  return (
    <MapContainer bounds={b} maxZoom={22} zoomSnap={0.25} className="h-[420px] w-full rounded-xl md:h-[520px]" scrollWheelZoom={false}>
      <Fit bounds={b} />
      {context && <TileLayer url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" maxNativeZoom={19} maxZoom={22} attribution="© OpenStreetMap contributors" />}
      {images.rgb && <ImageOverlay key={images.rgb} url={images.rgb} bounds={b} />}
      {active !== 'none' && images[active] && (
        <ImageOverlay key={images[active]} url={images[active]} bounds={b} opacity={active === 'ndvi' || active === 'ndre' ? 0.85 : 1} />
      )}
      {outlines &&
        hotspots.map((h) => {
          const sel = h.id === selected
          const feature: Feature = { type: 'Feature', properties: {}, geometry: h.geometry }
          return (
            <GeoJSON
              key={`${h.id}-${sel}`}
              data={feature}
              style={{ color: priorityColor(h.priority), weight: sel ? 4 : 2, fillOpacity: sel ? 0.18 : 0.04, dashArray: sel ? undefined : '4 3' }}
              eventHandlers={{ click: () => onSelect(h.id) }}
            />
          )
        })}
    </MapContainer>
  )
}
