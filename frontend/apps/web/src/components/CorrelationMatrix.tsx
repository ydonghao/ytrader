/**
 * CorrelationMatrix — holdings NxN correlation heatmap.
 *
 * Pattern borrowed from MonthlyHeatmap (CSS Grid + getColor), but uses
 * the Apple-dark CSS variables from styles/global.css via color-mix()
 * instead of hardcoded RGB — strong positive = red (--color-danger),
 * strong negative = blue (--color-accent), ~0 = neutral fill.
 */
import { useState, Fragment, type CSSProperties } from 'react';
import './CorrelationMatrix.css';

interface CorrelationMatrixProps {
  symbols: string[];
  matrix: number[][];
}

interface HoverCell {
  a: string;
  b: string;
  value: number;
  x: number;
  y: number;
}

/**
 * Map a correlation coefficient in [-1, 1] to a background color.
 * intensity = abs(corr); sign picks the hue (red + / blue -).
 */
function getCellColor(corr: number): string {
  const intensity = Math.min(Math.abs(corr), 1);
  if (intensity < 0.05) return 'var(--color-fill-secondary)';
  const pct = Math.round(intensity * 100);
  const tint = corr > 0 ? 'var(--color-danger)' : 'var(--color-accent)';
  return `color-mix(in srgb, ${tint} ${pct}%, var(--color-fill))`;
}

function getCellTextColor(corr: number): string {
  return Math.abs(corr) > 0.45 ? 'var(--color-text)' : 'var(--color-text-secondary)';
}

export function CorrelationMatrix({ symbols, matrix }: CorrelationMatrixProps) {
  const [hover, setHover] = useState<HoverCell | null>(null);
  const n = symbols.length;

  if (n === 0 || matrix.length === 0) return null;

  const gridStyle: CSSProperties = {
    gridTemplateColumns: `var(--cm-label-w) repeat(${n}, var(--cm-cell-size))`,
  };

  return (
    <div className="correlation-matrix">
      <div className="correlation-matrix__legend">
        <span className="correlation-matrix__legend-item">
          <span
            className="correlation-matrix__legend-swatch"
            style={{ background: 'var(--color-accent)' }}
          />
          负相关 −1
        </span>
        <span className="correlation-matrix__legend-item">
          <span
            className="correlation-matrix__legend-swatch"
            style={{ background: 'var(--color-fill-secondary)' }}
          />
          无相关 0
        </span>
        <span className="correlation-matrix__legend-item">
          <span
            className="correlation-matrix__legend-swatch"
            style={{ background: 'var(--color-danger)' }}
          />
          正相关 +1
        </span>
      </div>

      <div className="correlation-matrix__grid-wrap">
        <div className="correlation-matrix__grid" style={gridStyle}>
          {/* corner */}
          <div className="correlation-matrix__corner" />

          {/* column headers */}
          {symbols.map((s, j) => (
            <div key={`col-${j}`} className="correlation-matrix__col-label" title={s}>
              {s}
            </div>
          ))}

          {/* rows */}
          {symbols.map((rowSym, i) => {
            const row = matrix[i] ?? [];
            return (
              <Fragment key={`row-${i}`}>
                <div className="correlation-matrix__row-label" title={rowSym}>
                  {rowSym}
                </div>
                {symbols.map((colSym, j) => {
                  const val = row[j];
                  const defined = typeof val === 'number';
                  const isDiagonal = i === j;
                  return (
                    <div
                      key={`cell-${i}-${j}`}
                      className={`correlation-matrix__cell${isDiagonal ? ' correlation-matrix__cell--diag' : ''}`}
                      style={{
                        background: isDiagonal
                          ? 'var(--color-surface-elevated)'
                          : defined ? getCellColor(val) : 'var(--color-fill)',
                        color: isDiagonal
                          ? 'var(--color-text-tertiary)'
                          : defined ? getCellTextColor(val) : 'var(--color-text-tertiary)',
                      }}
                      onMouseEnter={(e) => {
                        if (defined && !isDiagonal) setHover({ a: rowSym, b: colSym, value: val, x: e.clientX, y: e.clientY });
                      }}
                      onMouseMove={(e) => {
                        if (!defined || isDiagonal) return;
                        setHover((h) => (h ? { ...h, x: e.clientX, y: e.clientY } : h));
                      }}
                      onMouseLeave={() => setHover(null)}
                    >
                      {isDiagonal ? '—' : defined ? val.toFixed(2) : '—'}
                    </div>
                  );
                })}
              </Fragment>
            );
          })}
        </div>
      </div>

      {hover && (
        <div
          className="correlation-matrix__tooltip"
          style={{ left: hover.x + 12, top: hover.y - 36, position: 'fixed' }}
        >
          {hover.a} vs {hover.b}: {hover.value.toFixed(2)}
        </div>
      )}
    </div>
  );
}
