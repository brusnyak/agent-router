// Router oversight widget: replaces the 8-glyph worker history with plain inline state,
// plus an on-demand `/router` command showing detailed task lines.
// Reads `python -m backbone status` (read-only SQLite, no network, no DB writes).
import { execFile } from 'node:child_process'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { truncateToWidth } from '@oh-my-pi/pi-tui'

const POLL_MS = 5000
const HOME = process.env.BACKBONE_HOME || join(homedir(), 'Developer', 'agent-router')
const BIN = process.env.BACKBONE_BIN || join(HOME, '.venv', 'bin', 'python')
const BRIEF = ['-m', 'backbone.status', '--brief']
const DETAILS = ['-m', 'backbone.status', '--details']

function runOnce(args: string[]): Promise<string> {
  return new Promise((resolve) => {
    execFile(BIN, args, { cwd: HOME, timeout: 8000, maxBuffer: 1 << 20 }, (error, stdout) => {
      if (error) resolve('Router unavailable')
      else resolve(String(stdout || '').replace(/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/g, '').trim())
    })
  })
}

function linesOf(text: string): string[] {
  return text.split('\n').map((l) => l.replace(/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/g, '').trim()).filter(Boolean)
}

export default function (pi: any) {
  let timer: any = null
  let generation = 0

  const stop = () => {
    generation++
    if (timer) { clearTimeout(timer); timer = null }
  }

  const tick = async (ctx: any, token: number) => {
    if (token !== generation) return
    try {
      const text = await runOnce(BRIEF)
      if (token !== generation) return
      let lines = linesOf(text)
      if (!lines.length) lines = ['Router unavailable']
      if (ctx.ui?.setWidget) ctx.ui.setWidget('router-status', () => ({
        render: (width: number) => lines.map(line => truncateToWidth(line, width)),
        invalidate() {},
      }), { placement: 'aboveEditor' })
    } catch {
      if (ctx.ui?.setWidget) ctx.ui.setWidget('router-status', ['Router unavailable'], { placement: 'aboveEditor' })
    } finally {
      if (token === generation) timer = setTimeout(() => tick(ctx, token), POLL_MS)
    }
  }

  pi.on('session_start', (_event, ctx) => {
    stop()
    if (ctx.hasUI !== false) void tick(ctx, generation)
  })

  pi.on('session_shutdown', stop)

  pi.registerCommand('router', {
    description: 'Show router status details (active tasks, counts, hosts)',
    handler: async (_args, ctx) => {
      try {
        const text = await runOnce(DETAILS)
        let lines = linesOf(text)
        if (!lines.length) lines = ['Router unavailable']
        if (ctx.ui?.select) {
          await ctx.ui.select('Router details', lines) // native select: read-only, preserves editor/focus
        } else if (ctx.ui?.notify) {
          ctx.ui.notify(lines.join('\n').slice(0, 2000), 'info')
        }
      } catch {
        if (ctx.ui?.notify) ctx.ui.notify('Router unavailable', 'error')
        else if (ctx.ui?.setWidget) ctx.ui.setWidget('router-status', ['Router unavailable'], { placement: 'aboveEditor' })
      }
    },
  })

  return { stop }
}
