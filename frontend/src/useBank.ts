import { useCallback, useEffect, useRef, useState } from 'react'
import type { Snapshot } from './types'

export async function api(path: string, body?: unknown, method = 'GET') {
  let response: Response
  try {
    response = await fetch('/api' + path, {
      method,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new Error('Backend unreachable')
  }
  if (!response.ok) {
    let detail = ''
    try {
      const data = JSON.parse(await response.text())
      if (data?.detail != null) detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)
    } catch {}
    throw new Error(`HTTP ${response.status}${detail ? ' · ' + detail : ''}`)
  }
  try {
    return JSON.parse(await response.text())
  } catch {
    throw new Error('Backend unreachable')
  }
}

const empty: Snapshot = { overview: null, integrity: null, payments: [], settlements: [], ledger: [], incidents: [], audit: [] }

export function useBank() {
  const [data, setData] = useState<Snapshot>(empty)
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState('')
  const refreshRef = useRef<() => Promise<void>>(async () => {})
  const refresh = useCallback(() => refreshRef.current(), [])

  useEffect(() => {
    let alive = true, running = false, queued = false
    let timer: ReturnType<typeof setTimeout> | undefined
    let version = 0
    async function load() {
      if (running) { queued = true; return }
      running = true
      const requestedVersion = version
      try {
        const [overview, integrity, payments, settlements, ledger, incidents, audit] = await Promise.all(
          ['/overview', '/integrity', '/payments?limit=50', '/settlements?limit=50',
            '/ledger?limit=500', '/incidents', '/audit?limit=100'].map(path => api(path)),
        )
        if (alive && version === requestedVersion) {
          setData({ overview, integrity, payments, settlements, ledger, incidents, audit })
          setError('')
        } else if (alive) queued = true
      } catch (cause) {
        if (alive) setError(cause instanceof Error ? cause.message : 'Backend unavailable')
      } finally {
        running = false
        if (alive && queued) { queued = false; schedule() }
      }
    }
    function schedule() {
      clearTimeout(timer)
      timer = setTimeout(() => { void load() }, 70)
    }
    refreshRef.current = load
    void load()
    const stream = new EventSource('/api/stream')
    stream.onopen = () => { setConnected(true); void load() }
    stream.onerror = () => { setConnected(false) }
    const onEvent = () => { version += 1; schedule() }
    for (const name of ['payment.accepted', 'settlement.posted', 'integrity.updated',
      'incident.updated', 'service.updated', 'audit.appended', 'reset']) {
      stream.addEventListener(name, onEvent)
    }
    return () => { alive = false; clearTimeout(timer); stream.close() }
  }, [])

  return { data, connected, error, refresh }
}
