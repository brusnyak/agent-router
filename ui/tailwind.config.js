/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        primary: '#007ACC',
        secondary: '#CCA700',
        tertiary: '#89D185',
        neutral: '#1E1E1E',
        sidebar: '#252526',
        card: '#181818',
        border: '#2B2B2B',
        text: '#CCCCCC',
        textSecondary: '#858585',
        textTertiary: '#5A5A5A',
      },
      fontFamily: {
        sans: ['Geist', 'system-ui', 'sans-serif'],
        mono: ['Geist Mono', 'monospace'],
      },
    },
  },
  plugins: [],
}
