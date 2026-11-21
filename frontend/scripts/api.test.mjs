import assert from 'node:assert/strict'
import { test } from 'node:test'
import { api } from '../src/useBank.ts'

test('API JSON success and POST body', async t => {
  t.mock.method(globalThis, 'fetch', async (url, init) => {
    assert.equal(url, '/api/test')
    assert.equal(init.method, 'POST')
    assert.equal(init.headers['Content-Type'], 'application/json')
    assert.equal(init.body, '{"actor":"ops.lead@bank"}')
    return new Response('{"status":"ok"}')
  })
  assert.deepEqual(await api('/test', { actor: 'ops.lead@bank' }, 'POST'), { status: 'ok' })
})

for (const [name, status, body, message] of [
  ['HTML outage', 503, '<html>Unavailable</html>', 'HTTP 503'],
  ['empty outage', 502, '', 'HTTP 502'],
  ['null error', 500, 'null', 'HTTP 500'],
  ['authorization detail', 403, '{"detail":"Actor is not an authorized approver"}', 'HTTP 403 · Actor is not an authorized approver'],
  ['validation detail', 422, '{"detail":[{"msg":"Invalid variant"}]}', 'HTTP 422 · [{"msg":"Invalid variant"}]'],
  ['malformed success', 200, '<html>Proxy offline</html>', 'Backend unreachable'],
  ['empty success', 200, '', 'Backend unreachable'],
]) {
  test(name, async t => {
    t.mock.method(globalThis, 'fetch', async () => new Response(body, { status }))
    await assert.rejects(api('/test'), { message })
  })
}

test('network outage', async t => {
  t.mock.method(globalThis, 'fetch', async () => { throw new TypeError('Failed to fetch') })
  await assert.rejects(api('/test'), { message: 'Backend unreachable' })
})

test('unreadable HTTP error body', async t => {
  t.mock.method(globalThis, 'fetch', async () => ({
    ok: false, status: 502, text: async () => { throw new Error('Connection closed') },
  }))
  await assert.rejects(api('/test'), { message: 'HTTP 502' })
})
