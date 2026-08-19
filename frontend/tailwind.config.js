/**
 * Design tokens for the AML investigator console.
 *
 * Visual language: deep navy/charcoal surfaces, restrained borders, and colour
 * used ONLY to carry meaning. Risk colours are semantic (green = low,
 * amber = medium, red = high/critical, blue = informational, slate = neutral)
 * and are always paired with a text label or icon in the UI, never used alone.
 */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        // Base surfaces - deep navy, not pure black
        ink: {
          950: '#070b14',
          900: '#0b1220',
          850: '#0f1729',
          800: '#131c31',
          750: '#18233c',
          700: '#1e2b47',
          600: '#2a3a5c',
          500: '#3b4d73',
        },
        // Neutral text/borders
        slateish: {
          400: '#8b9ab5',
          300: '#a9b6cc',
          200: '#c9d3e3',
          100: '#e6ebf4',
        },
        // Semantic risk palette
        risk: {
          low: '#22a06b',
          lowBg: 'rgba(34, 160, 107, 0.12)',
          medium: '#d99524',
          mediumBg: 'rgba(217, 149, 36, 0.13)',
          high: '#e0533d',
          highBg: 'rgba(224, 83, 61, 0.13)',
          critical: '#c02a3f',
          criticalBg: 'rgba(192, 42, 63, 0.16)',
        },
        info: {
          DEFAULT: '#3d8bfd',
          soft: 'rgba(61, 139, 253, 0.13)',
        },
        accent: {
          DEFAULT: '#4fd1c5',
          soft: 'rgba(79, 209, 197, 0.12)',
        },
      },
      fontFamily: {
        sans: [
          'Inter',
          'ui-sans-serif',
          'system-ui',
          '-apple-system',
          'Segoe UI',
          'Roboto',
          'Helvetica Neue',
          'Arial',
          'sans-serif',
        ],
        mono: [
          'JetBrains Mono',
          'ui-monospace',
          'SFMono-Regular',
          'Menlo',
          'Consolas',
          'monospace',
        ],
      },
      fontSize: {
        // Dense, information-first type scale
        '2xs': ['0.6875rem', { lineHeight: '1rem' }],
        xs: ['0.75rem', { lineHeight: '1.1rem' }],
        sm: ['0.8125rem', { lineHeight: '1.25rem' }],
        base: ['0.875rem', { lineHeight: '1.375rem' }],
      },
      boxShadow: {
        card: '0 1px 2px rgba(0, 0, 0, 0.35), 0 0 0 1px rgba(255, 255, 255, 0.04)',
        raised: '0 8px 24px -8px rgba(0, 0, 0, 0.6), 0 0 0 1px rgba(255, 255, 255, 0.05)',
        drawer: '-12px 0 40px -12px rgba(0, 0, 0, 0.7)',
      },
      borderRadius: {
        card: '0.625rem',
      },
      keyframes: {
        'fade-in': {
          from: { opacity: '0' },
          to: { opacity: '1' },
        },
        'slide-up': {
          from: { opacity: '0', transform: 'translateY(6px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        'slide-in-right': {
          from: { transform: 'translateX(100%)' },
          to: { transform: 'translateX(0)' },
        },
        shimmer: {
          '100%': { transform: 'translateX(100%)' },
        },
        'pulse-soft': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.55' },
        },
      },
      animation: {
        // Deliberately short: motion should orient, never entertain
        'fade-in': 'fade-in 140ms ease-out',
        'slide-up': 'slide-up 180ms ease-out',
        'slide-in-right': 'slide-in-right 220ms cubic-bezier(0.32, 0.72, 0, 1)',
        shimmer: 'shimmer 1.6s infinite',
        'pulse-soft': 'pulse-soft 2.4s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}
