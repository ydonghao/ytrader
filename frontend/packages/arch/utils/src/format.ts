/**
 * Formatting utilities
 */

/**
 * Format a number as currency
 */
export const formatCurrency = (
  value: number,
  currency: string = 'USD',
  locale: string = 'en-US'
): string => {
  return new Intl.NumberFormat(locale, {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
};

/**
 * Format a number with specified decimal places
 */
export const formatNumber = (
  value: number,
  decimals: number = 2,
  locale: string = 'en-US'
): string => {
  return new Intl.NumberFormat(locale, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value);
};

/**
 * Format a percentage value
 */
export const formatPercent = (
  value: number,
  decimals: number = 2,
  showSign: boolean = true
): string => {
  const formatted = formatNumber(value, decimals);
  if (showSign && value > 0) {
    return `+${formatted}%`;
  }
  return `${formatted}%`;
};

/**
 * Format a price with appropriate precision based on value
 */
export const formatPrice = (price: number): string => {
  if (price >= 1000) {
    return formatNumber(price, 2);
  } else if (price >= 1) {
    return formatNumber(price, 4);
  } else if (price >= 0.0001) {
    return formatNumber(price, 6);
  } else {
    return formatNumber(price, 8);
  }
};

/**
 * Format trading volume
 */
export const formatVolume = (volume: number): string => {
  if (volume >= 1_000_000_000) {
    return `${formatNumber(volume / 1_000_000_000, 2)}B`;
  } else if (volume >= 1_000_000) {
    return `${formatNumber(volume / 1_000_000, 2)}M`;
  } else if (volume >= 1_000) {
    return `${formatNumber(volume / 1_000, 2)}K`;
  }
  return formatNumber(volume, 2);
};

/**
 * Abbreviate large numbers
 */
export const abbreviateNumber = (value: number): string => {
  const suffixes = ['', 'K', 'M', 'B', 'T', 'Q'];
  let tier = 0;
  let scaled = value;

  while (scaled >= 1000 && tier < suffixes.length - 1) {
    scaled /= 1000;
    tier++;
  }

  return `${formatNumber(scaled, 2)}${suffixes[tier]}`;
};

/**
 * Format a date for display
 */
export const formatDate = (
  date: Date | number,
  options: Intl.DateTimeFormatOptions = {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }
): string => {
  const d = typeof date === 'number' ? new Date(date) : date;
  return new Intl.DateTimeFormat('en-US', options).format(d);
};

/**
 * Format relative time (e.g., "2 hours ago")
 */
export const formatRelativeTime = (timestamp: number): string => {
  const now = Date.now();
  const diff = now - timestamp;
  const seconds = Math.floor(diff / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);

  if (days > 0) return `${days}d ago`;
  if (hours > 0) return `${hours}h ago`;
  if (minutes > 0) return `${minutes}m ago`;
  return 'Just now';
};
