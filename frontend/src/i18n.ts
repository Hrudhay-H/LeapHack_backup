export type Lang = 'en' | 'kn'

// Kannada strings are illustrative and need review by a Kannada-speaking agricultural expert.
const dict = {
  hello: { en: 'Hello', kn: 'ನಮಸ್ಕಾರ' },
  cropHealth: { en: 'Crop health', kn: 'ಬೆಳೆ ಆರೋಗ್ಯ' },
  cropAnalysed: { en: 'Crop area analysed', kn: 'ವಿಶ್ಲೇಷಿಸಿದ ಬೆಳೆ ಪ್ರದೇಶ' },
  areasToInspect: { en: 'Areas to inspect', kn: 'ಪರಿಶೀಲಿಸಬೇಕಾದ ಪ್ರದೇಶಗಳು' },
  suspiciousArea: { en: 'Suspicious area', kn: 'ಸಂಶಯಾಸ್ಪದ ಪ್ರದೇಶ' },
  shareOfCrop: { en: 'Share of crop', kn: 'ಬೆಳೆಯ ಶೇಕಡಾ' },
  noAnomaly: { en: 'No significant anomaly detected', kn: 'ಯಾವುದೇ ಗಮನಾರ್ಹ ಅಸಾಮಾನ್ಯತೆ ಕಂಡುಬಂದಿಲ್ಲ' },
  noAnomalyHelp: {
    en: 'This is a valid result, not a failed scan. Keep monitoring at the next survey.',
    kn: 'ಇದು ಮಾನ್ಯ ಫಲಿತಾಂಶ. ಮುಂದಿನ ಸಮೀಕ್ಷೆಯಲ್ಲಿ ಮತ್ತೆ ಗಮನಿಸಿ.',
  },
  viewReport: { en: 'View report', kn: 'ವರದಿ ನೋಡಿ' },
  downloadReport: { en: 'Download PDF', kn: 'ವರದಿ ಡೌನ್‌ಲೋಡ್' },
  map: { en: 'Field map', kn: 'ಜಮೀನಿನ ನಕ್ಷೆ' },
  layers: { en: 'Map layer', kn: 'ನಕ್ಷೆ ಪದರ' },
  hotspots: { en: 'Hotspots', kn: 'ಸಮಸ್ಯೆ ಪ್ರದೇಶಗಳು' },
  groundCheck: { en: 'Ground check', kn: 'ಹೊಲದ ಪರಿಶೀಲನೆ' },
  pest: { en: 'Pest damage seen', kn: 'ಕೀಟ ಹಾನಿ ಕಂಡಿದೆ' },
  notPest: { en: 'No pest damage', kn: 'ಕೀಟ ಹಾನಿ ಇಲ್ಲ' },
  other: { en: 'Other / not sure', kn: 'ಇತರೆ / ಖಚಿತವಿಲ್ಲ' },
  pending: { en: 'Pending inspection', kn: 'ಪರಿಶೀಲನೆ ಬಾಕಿ' },
  priority: { en: 'Inspection priority', kn: 'ಪರಿಶೀಲನೆ ಆದ್ಯತೆ' },
  confidence: { en: 'Detection confidence', kn: 'ಪತ್ತೆ ವಿಶ್ವಾಸ' },
  logout: { en: 'Log out', kn: 'ಲಾಗ್ ಔಟ್' },
  disclaimer: {
    en: 'Hotspots show where the crop looks unusual. They do not confirm pests or disease; ground inspection is needed.',
    kn: 'ಇವು ಬೆಳೆ ಅಸಾಮಾನ್ಯವಾಗಿ ಕಾಣುವ ಸ್ಥಳಗಳನ್ನು ಮಾತ್ರ ತೋರಿಸುತ್ತವೆ. ಕೀಟ ಅಥವಾ ರೋಗವನ್ನು ಖಚಿತಪಡಿಸಲು ಹೊಲದಲ್ಲಿ ಪರಿಶೀಲನೆ ಅಗತ್ಯ.',
  },
  P_CRITICAL: { en: 'Critical', kn: 'ತುರ್ತು' },
  P_HIGH: { en: 'High', kn: 'ಹೆಚ್ಚು' },
  P_MODERATE: { en: 'Moderate', kn: 'ಮಧ್ಯಮ' },
  P_LOW: { en: 'Low', kn: 'ಕಡಿಮೆ' },
  C_HIGH: { en: 'High', kn: 'ಹೆಚ್ಚು' },
  C_MEDIUM: { en: 'Medium', kn: 'ಮಧ್ಯಮ' },
  C_LOW: { en: 'Low', kn: 'ಕಡಿಮೆ' },
} as const

export type Key = keyof typeof dict

export function tr(lang: Lang, key: Key): string {
  return dict[key][lang]
}

export const PRIORITY_COLOR: Record<string, string> = {
  CRITICAL: '#b91c1c',
  HIGH: '#ea580c',
  MODERATE: '#ca8a04',
  LOW: '#6b7280',
}
