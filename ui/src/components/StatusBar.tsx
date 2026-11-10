import React from 'react'

export function StatusBar() {
  return (
    <div className="status-bar">
      <span className="flex items-center gap-2">
        <span className="w-2 h-2 rounded-full bg-[#89D185"]></span>
        <span>All agents online</span>
      </span>
      <span className="flex items-center gap-2">
        <span>RAM 64% · SSD 66%</span>
        <span className="w-px h-3 bg-[var(--border-subtle)] mx-1"></span>
        <span>Sensor 9W</span>
      </span>
      <span className="flex items-center gap-2">
        <span className="font-mono">Tue 10 Nov 04:42</span>
      </span>
    </div>
  )
}
