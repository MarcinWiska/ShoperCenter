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
          primary: '#ef4444',        // Red-500
          'primary-focus': '#dc2626', // Red-600
          'primary-content': '#ffffff',
          secondary: '#7f1d1d',       // Red-900
          'secondary-focus': '#991b1b', // Red-800
          'secondary-content': '#ffffff',
          accent: '#fca5a5',          // Red-300
          'accent-focus': '#f87171',  // Red-400
          'accent-content': '#7f1d1d',
          neutral: '#1e293b',         // Slate-800
          'neutral-focus': '#0f172a', // Slate-900
          'neutral-content': '#e2e8f0',
          'base-100': '#020617',      // Slate-950 - darkest background
          'base-200': '#0f172a',      // Slate-900
          'base-300': '#1e293b',      // Slate-800
          'base-content': '#f1f5f9',  // Slate-100 - light text
          info: '#38bdf8',            // Sky-400
          'info-content': '#0c4a6e',
          success: '#22c55e',         // Green-500
          'success-content': '#14532d',
          warning: '#f59e0b',         // Amber-500
          'warning-content': '#78350f',
          error: '#ef4444',           // Red-500
          'error-content': '#7f1d1d',
          '--rounded-box': '1rem',
          '--rounded-btn': '0.75rem',
          '--rounded-badge': '1rem',
          '--animation-btn': '0.2s',
          '--animation-input': '0.2s',
          '--btn-text-case': 'none',
          '--border-btn': '1px',
          '--tab-border': '1px',
        },
      },
    ],
    darkTheme: 'shoperdark',
    base: true,
    styled: true,
    utils: true,
    logs: false,
  },
  darkMode: ['class', '[data-theme="shoperdark"]'],
}
