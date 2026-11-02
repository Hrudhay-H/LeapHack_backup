import type { Lang } from './i18n'
import type { SurveyDetail } from './types'

/** Plain-language script an operator can read out to a farmer. Rule-based; no AI generation involved. */
const CROP_KN: Record<string, string> = { paddy: 'ಭತ್ತದ', maize: 'ಮೆಕ್ಕೆಜೋಳದ' } // needs expert review

export function explain(lang: Lang, name: string, s: SurveyDetail): string {
  const sm = s.summary
  const crop = (s.farm.crop || 'crop').toLowerCase()
  const cropKn = CROP_KN[crop] ?? ''
  if (sm.hotspots_detected === 0) {
    return lang === 'kn'
      ? `${name} ಅವರೇ, ನಿಮ್ಮ ${cropKn} ಬೆಳೆಯ ಸಮೀಕ್ಷೆಯಲ್ಲಿ ಯಾವುದೇ ಗಮನಾರ್ಹ ಸಮಸ್ಯೆ ಕಂಡುಬಂದಿಲ್ಲ. ಮುಂದಿನ ಸಮೀಕ್ಷೆಯವರೆಗೆ ಬೆಳೆಯನ್ನು ಗಮನಿಸುತ್ತಿರಿ.`
      : `${name}, no significant problem areas were found in your ${crop} survey. Keep watching the crop until the next survey.`
  }
  const top = s.hotspots[0]
  return lang === 'kn'
    ? `${name} ಅವರೇ, ನಿಮ್ಮ ಬೆಳೆಯ ${sm.suspicious_area_percent}% ಭಾಗದಲ್ಲಿ ${sm.hotspots_detected} ಪ್ರದೇಶಗಳು ಅಸಾಮಾನ್ಯವಾಗಿ ಕಾಣುತ್ತಿವೆ. ` +
        `ಮೊದಲು ನಕ್ಷೆಯ ಸಂಖ್ಯೆ 1 ಪ್ರದೇಶವನ್ನು ನೋಡಿ (ಸುಮಾರು ${Math.round(top.estimated_area_sqm)} ಚದರ ಮೀಟರ್). ` +
        `ಇದು ಕೀಟವೇ ಎಂದು ಈಗಲೇ ಹೇಳಲಾಗದು; ಹೊಲದಲ್ಲಿ ಹೋಗಿ ಪರಿಶೀಲಿಸಬೇಕು.`
    : `${name}, ${sm.hotspots_detected} area(s) covering ${sm.suspicious_area_percent}% of your crop look unusual. ` +
        `Please check area number 1 first (about ${Math.round(top.estimated_area_sqm)} square metres). ` +
        `We cannot say yet that it is a pest; someone must walk to the spot and look.`
}
