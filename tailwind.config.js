/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./shops/templates/**/*.html",
    "./accounts/templates/**/*.html",
    "./modules/templates/**/*.html",
    "./seo_redirects/templates/**/*.html",
  ],
  theme: {
    extend: {
      colors: {
        'shoper': {
          50: '#fef2f2',
          100: '#fee2e2',
          200: '#fecaca',
          300: '#fca5a5',
          400: '#f87171',
          500: '#ef4444',
          600: '#dc2626',
          700: '#b91c1c',
          800: '#991b1b',
          900: '#7f1d1d',
          950: '#450a0a',
        },
        'dark': {
          50: '#f8fafc',
          100: '#f1f5f9',
          200: '#e2e8f0',
          300: '#cbd5e1',
          400: '#94a3b8',
          500: '#64748b',
          600: '#475569',
          700: '#334155',
          800: '#1e293b',
          850: '#1a2332',
          900: '#0f172a',
          950: '#020617',
        }
      },
      fontFamily: {
        'sans': ['Inter', 'system-ui', 'sans-serif'],
      },
      boxShadow: {
        'glow': '0 0 20px rgba(239, 68, 68, 0.3)',
        'glow-lg': '0 0 30px rgba(239, 68, 68, 0.4)',
        'inner-glow': 'inset 0 0 10px rgba(239, 68, 68, 0.1)',
      },
      animation: {
        'fade-in': 'fadeIn 0.5s ease-in-out',
        'slide-in': 'slideIn 0.3s ease-out',
        'pulse-glow': 'pulseGlow 2s infinite',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0', transform: 'translateY(10px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        slideIn: {
          '0%': { transform: 'translateX(-100%)' },
          '100%': { transform: 'translateX(0)' },
        },
        pulseGlow: {
          '0%, 100%': { boxShadow: '0 0 20px rgba(239, 68, 68, 0.3)' },
          '50%': { boxShadow: '0 0 30px rgba(239, 68, 68, 0.6)' },
        },
      },
      backdropBlur: {
        xs: '2px',
      },
      spacing: {
        '18': '4.5rem',
        '88': '22rem',
      }
    },
  },
  plugins: [require('daisyui')],
  daisyui: {
    themes: [
      {
        shoperdark: {
          ...require('daisyui/src/theming/themes')['dark'],
          primary: '#ef4444',
          'primary-content': '#ffffff',
          secondary: '#7f1d1d',
          accent: '#fca5a5',
          neutral: '#1e293b',
          'neutral-content': '#cbd5e1',
          'base-100': '#0f172a',
          'base-200': '#1e293b',
          'base-300': '#334155',
          'base-content': '#f1f5f9',
          info: '#38bdf8',
          success: '#22c55e',
          warning: '#f59e0b',
          error: '#ef4444',
        },
      },
    ],
    darkTheme: 'shoperdark',
  },
}
