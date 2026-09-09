/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["../js/*.js", "../../html/*.html", "../../html/**/*.html"],
  theme: {
    extend: {
      colors: { // 自定义颜色体系
        primary: '#165DFF', // 主色调（深蓝色）
        secondary: '#36CFC9', // 辅助色（青绿色）
        accent: '#722ED1', // 强调色（紫色）
        neutral: '#F5F7FA', // 中性色（浅灰背景）
        dark: '#1D2129', // 深色（文本/背景）
      },
      fontFamily: { // 自定义字体
        inter: ['Inter', 'system-ui', 'sans-serif'],
      },
    },
  },
  safelist: [
    // 所有可能出现在卡片中的背景色和文字色
    'bg-blue-100', 'bg-red-100', 'bg-orange-100', 'bg-green-100', 'bg-purple-100',
    'text-blue-600', 'text-red-600', 'text-yellow-600', 'text-green-600', 'text-purple-600',
  ],
  plugins: [],
}

