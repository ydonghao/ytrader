/**
 * Validation utilities
 */

/**
 * Validate trading symbol format (e.g., BTCUSDT)
 */
export const isValidSymbol = (symbol: string): boolean => {
  return /^[A-Z]{2,10}(USDT|BUSD|BTC|ETH|BNB)$/.test(symbol);
};

/**
 * Validate price
 */
export const isValidPrice = (price: number): boolean => {
  return !isNaN(price) && isFinite(price) && price > 0;
};

/**
 * Validate quantity
 */
export const isValidQuantity = (quantity: number, min: number = 0, max?: number): boolean => {
  if (isNaN(quantity) || !isFinite(quantity) || quantity < min) {
    return false;
  }
  if (max !== undefined && quantity > max) {
    return false;
  }
  return true;
};

/**
 * Validate order side
 */
export const isValidSide = (side: string): side is 'BUY' | 'SELL' => {
  return side === 'BUY' || side === 'SELL';
};

/**
 * Validate order type
 */
export const isValidOrderType = (
  type: string
): type is 'LIMIT' | 'MARKET' | 'STOP_LOSS' | 'TAKE_PROFIT' => {
  return ['LIMIT', 'MARKET', 'STOP_LOSS', 'TAKE_PROFIT'].includes(type);
};

/**
 * Validate leverage value
 */
export const isValidLeverage = (leverage: number, maxLeverage: number = 125): boolean => {
  return Number.isInteger(leverage) && leverage >= 1 && leverage <= maxLeverage;
};

/**
 * Validate stop loss / take profit price
 */
export const isValidStopPrice = (
  price: number,
  entryPrice: number,
  side: 'BUY' | 'SELL',
  type: 'STOP_LOSS' | 'TAKE_PROFIT'
): boolean => {
  if (!isValidPrice(price)) return false;

  if (type === 'STOP_LOSS') {
    return side === 'BUY' ? price < entryPrice : price > entryPrice;
  } else {
    return side === 'BUY' ? price > entryPrice : price < entryPrice;
  }
};

/**
 * Validate email format
 */
export const isValidEmail = (email: string): boolean => {
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  return emailRegex.test(email);
};

/**
 * Validate API key format
 */
export const isValidApiKey = (key: string): boolean => {
  // Basic check - should be alphanumeric with possible special chars
  return key.length >= 16 && /^[a-zA-Z0-9_-]+$/.test(key);
};

/**
 * Validate URL format
 */
export const isValidUrl = (url: string): boolean => {
  try {
    new URL(url);
    return true;
  } catch {
    return false;
  }
};

/**
 * Validate date range
 */
export const isValidDateRange = (start: Date, end: Date): boolean => {
  return start instanceof Date && end instanceof Date && start < end;
};

/**
 * Get validation error message
 */
export const getValidationError = (
  field: string,
  value: unknown,
  rules: {
    required?: boolean;
    min?: number;
    max?: number;
    minLength?: number;
    maxLength?: number;
    pattern?: RegExp;
  }
): string | null => {
  const {required, min, max, minLength, maxLength, pattern} = rules;

  if (required && (value === undefined || value === null || value === '')) {
    return `${field} is required`;
  }

  if (typeof value === 'number') {
    if (min !== undefined && value < min) {
      return `${field} must be at least ${min}`;
    }
    if (max !== undefined && value > max) {
      return `${field} must be at most ${max}`;
    }
  }

  if (typeof value === 'string') {
    if (minLength !== undefined && value.length < minLength) {
      return `${field} must be at least ${minLength} characters`;
    }
    if (maxLength !== undefined && value.length > maxLength) {
      return `${field} must be at most ${maxLength} characters`;
    }
    if (pattern && !pattern.test(value)) {
      return `${field} format is invalid`;
    }
  }

  return null;
};
