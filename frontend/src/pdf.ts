import { openBlob } from './api'

/** Open a PDF in a new tab without the popup blocker firing (tab is opened synchronously, filled when ready). */
export async function viewPdf(load: () => Promise<Blob>): Promise<void> {
  const w = window.open('', '_blank')
  try {
    const blob = await load()
    const url = URL.createObjectURL(new Blob([blob], { type: 'application/pdf' }))
    if (w) w.location.href = url
    else window.location.href = url
    setTimeout(() => URL.revokeObjectURL(url), 5 * 60_000)
  } catch (e) {
    w?.close()
    throw e
  }
}

export async function savePdf(load: () => Promise<Blob>, filename: string): Promise<void> {
  openBlob(await load(), filename)
}
