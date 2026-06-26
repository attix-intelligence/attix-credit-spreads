/**
 * @vitest-environment node
 */
import { describe, it, expect } from 'vitest'
import fs from 'fs'
import path from 'path'

describe('Production Readiness', () => {
  // The previous 'Dockerfile exists with multi-stage build' test was removed.
  // The repo deliberately deleted the root Dockerfile in commit 122267e
  // ("remove Dockerfile, use Nixpacks + Procfile for Railway"); production
  // deployment of the registry-driven worker uses Railpack (per Railway
  // serviceManifest.build.builder=RAILPACK), and service-specific Dockerfiles
  // like Dockerfile.scheduler live at repo root with explicit names. The web
  // app is not built from a root Dockerfile.

  it('.dockerignore exists', () => {
    const ignorePath = path.resolve(__dirname, '../../.dockerignore')
    expect(fs.existsSync(ignorePath)).toBe(true)
    const content = fs.readFileSync(ignorePath, 'utf-8')
    expect(content).toContain('node_modules')
    expect(content).toContain('.next')
  })

  it('next.config.js has standalone output', () => {
    const configPath = path.resolve(__dirname, '../next.config.js')
    const content = fs.readFileSync(configPath, 'utf-8')
    expect(content).toContain('standalone')
  })

  it('.env.example exists with required vars documented', () => {
    const envPath = path.resolve(__dirname, '../../.env.example')
    expect(fs.existsSync(envPath)).toBe(true)
    const content = fs.readFileSync(envPath, 'utf-8')
    expect(content).toContain('ALPACA_API_KEY')
    expect(content).toContain('POLYGON_API_KEY')
  })

  it('middleware.ts exists', () => {
    const mwPath = path.resolve(__dirname, '../middleware.ts')
    expect(fs.existsSync(mwPath)).toBe(true)
    const content = fs.readFileSync(mwPath, 'utf-8')
    expect(content).toContain('NextResponse')
    expect(content).toContain('matcher')
  })
})
