// Deterministic installed-OMP check. No LLM prompt, send, or database write.
import install from './router-status'
import { visibleWidth } from '@oh-my-pi/pi-tui'

export default function (pi: any) {
  pi.on('session_start', async (_: any, ctx: any) => {
    const handlers: Record<string, Function> = {}
    let command: any
    let updates = 0
    let panels = 0
    let first: () => void = () => {}
    let second: () => void = () => {}
    const firstUpdate = new Promise<void>(resolve => { first = resolve })
    const secondUpdate = new Promise<void>(resolve => { second = resolve })
    const check = (ok: boolean, message: string) => { if (!ok) throw new Error(message) }
    const fake = { hasUI: true, ui: {
      setWidget(_key: string, content: any) {
        check(typeof content === 'function', 'widget factory missing')
        const widget = content()
        for (const width of [40, 80, 120]) {
          const lines = widget.render(width)
          check(lines.length > 0, 'empty widget')
          check(lines.every((line: string) => visibleWidth(line) <= width), 'widget exceeds terminal width')
        }
        updates++
        if (updates === 1) first()
        if (updates === 2) second()
      },
      async select(_title: string, lines: string[]) {
        check(lines.length > 0, 'empty details')
        check(lines.some(line => line.includes('active tasks')), 'task details missing')
        panels++
      },
    } }
    install({ on(name: string, handler: Function) { handlers[name] = handler },
      registerCommand(name: string, spec: any) { check(name === 'router', 'wrong command'); command = spec } })
    try {
      handlers.session_start({}, fake)
      await firstUpdate
      await secondUpdate
      handlers.session_shutdown()
      check(updates === 2, 'polling did not restart')
      await command.handler('', fake)
      check(panels === 1, 'details command did not open')
      handlers.session_start({}, fake)
      handlers.session_shutdown()
      await new Promise(resolve => setTimeout(resolve, 100))
      check(updates === 2, 'late read repainted after shutdown')
      ctx.ui.notify('PASS router widget: 40/80/120 columns; polling; details; shutdown', 'info')
    } finally {
      handlers.session_shutdown()
    }
  })
}
