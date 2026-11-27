import React, { useEffect, useState } from 'react';

export interface NumericInputProps
  extends Omit<
    React.InputHTMLAttributes<HTMLInputElement>,
    'type' | 'value' | 'onChange' | 'defaultValue'
  > {
  value: number | null | undefined;
  onCommit: (next: number | null) => void;
  allowEmpty?: boolean;
  min?: number;
  max?: number;
  decimals?: number;
}

function formatNumeric(value: number | null | undefined, decimals?: number): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '';
  if (typeof decimals === 'number') return String(Number(value.toFixed(decimals)));
  return String(value);
}

/**
 * Controlled-on-commit numeric input that keeps a local string draft while focused
 * so multi-digit typing, minus signs, decimals, and temporary empty text never clamp mid-keystroke.
 */
export const NumericInput: React.FC<NumericInputProps> = ({
  value,
  onCommit,
  allowEmpty = false,
  min,
  max,
  decimals,
  onFocus,
  onBlur,
  onKeyDown,
  ...rest
}) => {
  const [focused, setFocused] = useState(false);
  const [draft, setDraft] = useState<string>(() => formatNumeric(value, decimals));

  useEffect(() => {
    if (!focused) {
      setDraft(formatNumeric(value, decimals));
    }
  }, [value, decimals, focused]);

  const commit = (raw: string) => {
    const trimmed = raw.trim();
    if (trimmed === '') {
      if (allowEmpty) {
        setDraft('');
        if (value !== null && value !== undefined) {
          onCommit(null);
        }
      } else {
        setDraft(formatNumeric(value, decimals));
      }
      return;
    }

    const parsed = Number(trimmed);
    if (!Number.isFinite(parsed)) {
      setDraft(formatNumeric(value, decimals));
      return;
    }

    let next = parsed;
    if (typeof min === 'number') next = Math.max(min, next);
    if (typeof max === 'number') next = Math.min(max, next);
    if (typeof decimals === 'number') next = Number(next.toFixed(decimals));

    setDraft(formatNumeric(next, decimals));
    onCommit(next);
  };

  return (
    <input
      {...rest}
      type="text"
      inputMode="decimal"
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onFocus={(e) => {
        setFocused(true);
        setDraft(formatNumeric(value, decimals));
        onFocus?.(e);
      }}
      onBlur={(e) => {
        setFocused(false);
        commit(e.currentTarget.value);
        onBlur?.(e);
      }}
      onKeyDown={(e) => {
        if (e.key === 'Enter') {
          commit(e.currentTarget.value);
          e.currentTarget.blur();
        } else if (e.key === 'Escape') {
          setDraft(formatNumeric(value, decimals));
          setFocused(false);
          e.currentTarget.blur();
        }
        onKeyDown?.(e);
      }}
    />
  );
};
