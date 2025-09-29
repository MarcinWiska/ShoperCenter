/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./shops/templates/**/*.html",
    "./accounts/templates/**/*.html",
  ],
  theme: {
    extend: {},
  },
  plugins: [require('daisyui')],
  daisyui: {
    themes: [
      {
        shoperdark: {
          ...require('daisyui/src/theming/themes')['dark'],
          primary: '#ef4444',
          'primary-content': '#ffffff',
          accent: '#fca5a5',
          secondary: '#7f1d1d',
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
