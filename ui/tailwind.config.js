/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        primary: 'var(--accent-primary)',
        secondary: 'var(--accent-secondary)',
        tertiary: 'var(--accent-tertiary)',
        neutral: 'var(--bg-window)',
        sidebar: 'var(--bg-sidebar)',
        card: 'var(--bg-card)',
        border: 'var(--border-subtle)',
        text: 'var(--fg-primary)',
        textSecondary: 'var(--fg-secondary)',
        textTertiary: 'var(--fg-tertiary)',
        danger: 'var(--danger)',
      },
      fontFamily: {
        sans: ['Geist', 'system-ui', 'sans-serif'],
        mono: ['Geist Mono', 'monospace'],
      },
    },
  },
  plugins: [],
}
