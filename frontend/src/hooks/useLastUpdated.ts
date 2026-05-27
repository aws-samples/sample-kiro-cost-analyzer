import { useState, useCallback } from 'react';
import { useI18n } from '../i18n/useI18n';

export interface UseLastUpdatedReturn {
  lastUpdated: Date | null;
  formattedTime: string | null;
  markUpdated: () => void;
}

export function useLastUpdated(): UseLastUpdatedReturn {
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const { formatTime } = useI18n();

  const markUpdated = useCallback(() => {
    setLastUpdated(new Date());
  }, []);

  const formattedTime = lastUpdated
    ? formatTime(lastUpdated, { hour: '2-digit', minute: '2-digit' })
    : null;

  return { lastUpdated, formattedTime, markUpdated };
}
