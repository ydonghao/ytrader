/**
 * @ytrader/arch-i18n
 * Internationalization for Trading Terminal
 */

import i18n from 'i18next';
import {initReactI18next} from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';

import {en} from './locales/en';
import {zhCN} from './locales/zh-CN';

export const resources = {
  en: {translation: en},
  'zh-CN': {translation: zhCN},
};

export const initI18n = (options?: {lng?: string; ns?: string[]}) => {
  i18n
    .use(LanguageDetector)
    .use(initReactI18next)
    .init({
      resources,
      fallbackLng: 'en',
      debug: false,
      interpolation: {
        escapeValue: false,
      },
      detection: {
        order: ['localStorage', 'navigator'],
        caches: ['localStorage'],
      },
      ...options,
    });

  return i18n;
};

export const changeLanguage = (lng: string) => i18n.changeLanguage(lng);

export const getCurrentLanguage = () => i18n.language;

export * from './locales/en';
export * from './locales/zh-CN';

export default i18n;
