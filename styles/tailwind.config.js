/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "../web/index.html",
    "../web/app.js",
  ],
  darkMode: ["selector", '[data-theme="dark"]'],
  corePlugins: {
    preflight: false,
  },
  theme: {
    extend: {},
  },
  plugins: [],
};
