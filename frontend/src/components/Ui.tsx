import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { PRIORITY_COLOR } from '../i18n'

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`rounded-xl border border-gray-200 bg-white p-4 shadow-sm ${className}`}>{children}</div>
}

export function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: string }) {
  return (
    <Card>
      <div className="text-xs font-medium uppercase tracking-wide text-gray-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-gray-900">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-gray-500">{sub}</div>}
    </Card>
  )
}

export function Chip({ children, color = '#6b7280' }: { children: ReactNode; color?: string }) {
  return (
    <span className="inline-block rounded-full px-2 py-0.5 text-xs font-semibold text-white" style={{ background: color }}>
      {children}
    </span>
  )
}

export const priorityColor = (p: string) => PRIORITY_COLOR[p] ?? '#6b7280'

export function Button({
  variant = 'primary',
  className = '',
  ...p
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'danger' }) {
  const styles = {
    primary: 'bg-brand-600 text-white hover:bg-brand-700 disabled:bg-gray-300',
    secondary: 'border border-gray-300 bg-white text-gray-800 hover:bg-gray-50 disabled:text-gray-400',
    danger: 'bg-red-600 text-white hover:bg-red-700 disabled:bg-gray-300',
  }[variant]
  return (
    <button
      {...p}
      className={`rounded-lg px-4 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed ${styles} ${className}`}
    />
  )
}

export function Banner({ tone, children }: { tone: 'warn' | 'info' | 'error' | 'ok'; children: ReactNode }) {
  const c = {
    warn: 'border-amber-300 bg-amber-50 text-amber-900',
    info: 'border-sky-300 bg-sky-50 text-sky-900',
    error: 'border-red-300 bg-red-50 text-red-900',
    ok: 'border-green-300 bg-green-50 text-green-900',
  }[tone]
  return <div className={`rounded-lg border px-3 py-2 text-sm ${c}`}>{children}</div>
}

export function TextInput(p: React.InputHTMLAttributes<HTMLInputElement> & { label: string }) {
  const { label, className = '', ...rest } = p
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium text-gray-700">{label}</span>
      <input
        {...rest}
        className={`w-full rounded-lg border border-gray-300 px-3 py-2 outline-none focus:border-brand-600 focus:ring-2 focus:ring-brand-100 ${className}`}
      />
    </label>
  )
}

export function Header({ title, sub, right }: { title: string; sub?: string; right?: ReactNode }) {
  return (
    <header className="border-b border-gray-200 bg-white">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-3 px-4 py-3">
        <a href="/" className="flex items-center gap-2">
          <span className="grid h-9 w-9 place-items-center rounded-lg bg-brand-600 text-lg text-white">🌾</span>
          <span>
            <span className="block text-base font-semibold leading-tight text-gray-900">{title}</span>
            {sub && <span className="block text-xs text-gray-500">{sub}</span>}
          </span>
        </a>
        <div className="flex items-center gap-3">{right}</div>
      </div>
    </header>
  )
}
