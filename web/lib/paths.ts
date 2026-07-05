import fs from 'fs'
import path from 'path'

/**
 * Root directory of the Python backend project.
 * Uses PROJECT_ROOT env var if set, otherwise falls back to process.cwd()/..
 * In Docker: /app (web runs from /app/web, Python from /app)
 * In dev: parent of the web/ directory
 */
export const PROJECT_ROOT = process.env.PROJECT_ROOT || path.join(process.cwd(), '..')

/** Path to config.yaml */
export const CONFIG_PATH = path.join(PROJECT_ROOT, 'config.yaml')

/**
 * Path to data/ directory.
 * Override via ATTIX_DATA_DIR env var for persistent volumes
 * (e.g. Railway volume mount at /app/data). The legacy PILOTAI_DATA_DIR
 * name is still honored for deployments that predate the rename.
 */
export const DATA_DIR = process.env.ATTIX_DATA_DIR || process.env.PILOTAI_DATA_DIR || path.join(PROJECT_ROOT, 'data')

/** Path to output/ directory */
export const OUTPUT_DIR = process.env.ATTIX_OUTPUT_DIR || process.env.PILOTAI_OUTPUT_DIR || path.join(PROJECT_ROOT, 'output')

/**
 * Resolve the SQLite database file inside a data directory.
 * Prefers attix.db; falls back to the legacy pilotai.db filename when only
 * that file exists (live deployments keep the old file on disk — it is
 * intentionally never renamed).
 */
export function resolveDbFile(dataDir: string): string {
  const attixPath = path.join(dataDir, 'attix.db')
  const legacyPath = path.join(dataDir, 'pilotai.db')
  try {
    if (!fs.existsSync(attixPath) && fs.existsSync(legacyPath)) {
      return legacyPath
    }
  } catch {
    // fall through to the attix default
  }
  return attixPath
}

/** Path to SQLite database */
export const DB_PATH = resolveDbFile(DATA_DIR)
