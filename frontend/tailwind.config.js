/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'Segoe UI', 'sans-serif'],
      },
      colors: {
        ink: '#17211b',
        field: '#f6f3ed',
        line: '#d8d2c5',
        moss: '#60745b',
        clay: '#a45f43',
      },
      boxShadow: {
        soft: '0 18px 45px rgba(36, 31, 22, 0.08)',
      },
    },
  },
  plugins: [],
};
