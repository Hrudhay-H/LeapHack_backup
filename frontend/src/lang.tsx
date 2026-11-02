import { createContext, useContext, useState, type ReactNode } from 'react'
import { tr, type Key, type Lang } from './i18n'

interface Ctx {
  lang: Lang
  setLang: (l: Lang) => void
  t: (k: Key) => string
}

const LangContext = createContext<Ctx>({ lang: 'en', setLang: () => {}, t: (k) => tr('en', k) })

export function LangProvider({ children }: { children: ReactNode }) {
  const [lang, setLang] = useState<Lang>('en')
  return <LangContext.Provider value={{ lang, setLang, t: (k) => tr(lang, k) }}>{children}</LangContext.Provider>
}

export const useLang = () => useContext(LangContext)

export function LangToggle() {
  const { lang, setLang } = useLang()
  return (
    <div className="inline-flex overflow-hidden rounded-full border border-gray-300 text-sm">
      {(['en', 'kn'] as const).map((l) => (
        <button
          key={l}
          onClick={() => setLang(l)}
          className={`px-3 py-1 ${lang === l ? 'bg-brand-600 text-white' : 'bg-white text-gray-700'}`}
        >
          {l === 'en' ? 'EN' : 'ಕನ್ನಡ'}
        </button>
      ))}
    </div>
  )
}
