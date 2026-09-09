/**
 * Theme hook for Trading Terminal
 */
import {useCallback} from 'react';
import {create} from 'zustand';
import {persist} from 'zustand/middleware';

export interface TradingTheme {
  colors: {
    background: string;
    surface: string;
    surfaceHover: string;
    border: string;
    text: string;
    textSecondary: string;
    accent: string;
    success: string;
    danger: string;
    warning: string;
  };
  fonts: {
    display: string;
    body: string;
    mono: string;
  };
  isDark: boolean;
}

// Apple Dark / Light palette — kept in sync with apps/web/src/styles/global.css
// so applyTheme() never overrides the canonical tokens with a foreign palette.
const darkTheme: TradingTheme = {
  colors: {
    background: '#1d1d1f',
    surface: '#2c2c2e',
    surfaceHover: '#3a3a3c',
    border: 'rgba(255, 255, 255, 0.08)',
    text: '#f5f5f7',
    textSecondary: '#a1a1a6',
    accent: '#0a84ff',
    success: '#30d158',
    danger: '#ff453a',
    warning: '#ffd60a',
  },
  fonts: {
    display: "'JetBrains Mono', monospace",
    body: "'Inter', -apple-system, sans-serif",
    mono: "'JetBrains Mono', monospace",
  },
  isDark: true,
};

const lightTheme: TradingTheme = {
  colors: {
    background: '#f5f5f7',
    surface: '#ffffff',
    surfaceHover: '#efefef',
    border: 'rgba(0, 0, 0, 0.10)',
    text: '#1d1d1f',
    textSecondary: '#6e6e73',
    accent: '#0071e3',
    success: '#34c759',
    danger: '#ff3b30',
    warning: '#ff9500',
  },
  fonts: {
    display: "'JetBrains Mono', monospace",
    body: "'Inter', -apple-system, sans-serif",
    mono: "'JetBrains Mono', monospace",
  },
  isDark: false,
};

interface ThemeState {
  theme: TradingTheme;
  setTheme: (theme: 'dark' | 'light') => void;
  toggleTheme: () => void;
}

export const useThemeStore = create<ThemeState>()(
  persist(
    set => ({
      theme: darkTheme,
      setTheme: themeType => set({theme: themeType === 'dark' ? darkTheme : lightTheme}),
      toggleTheme: () =>
        set(state => ({
          theme: state.theme.isDark ? lightTheme : darkTheme,
        })),
    }),
    {
      name: 'ytrader-theme',
    }
  )
);

export const useTheme = () => {
  const {theme, setTheme, toggleTheme} = useThemeStore();

  const applyTheme = useCallback(() => {
    const root = document.documentElement;
    Object.entries(theme.colors).forEach(([key, value]) => {
      root.style.setProperty(`--color-${key}`, value);
    });
    root.style.setProperty('--font-display', theme.fonts.display);
    root.style.setProperty('--font-body', theme.fonts.body);
    root.style.setProperty('--font-mono', theme.fonts.mono);
  }, [theme]);

  return {theme, setTheme, toggleTheme, applyTheme};
};
