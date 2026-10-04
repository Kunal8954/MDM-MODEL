import '@testing-library/jest-dom'
import { vi } from 'vitest'

// Default mock for fetch to prevent network hangs in test environment
(globalThis as any).fetch = vi.fn().mockImplementation(() =>
  Promise.resolve({
    ok: true,
    status: 200,
    statusText: 'OK',
    json: () => Promise.resolve({}),
  } as any)
)
