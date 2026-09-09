/**
 * Centralized API configuration.
 * Reads base URL from localStorage (set via Settings page) or falls back to proxy path.
 */

const STORAGE_KEY = 'ytrader_api_base';
const DEFAULT_BASE = '/api/v1';

export function getApiBase(): string {
  return localStorage.getItem(STORAGE_KEY) || DEFAULT_BASE;
}

export function getWsBase(): string {
  return getApiBase().replace(/^http/, 'ws').replace('/api/v1', '/ws');
}
