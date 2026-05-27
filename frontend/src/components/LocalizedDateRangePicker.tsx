import DateRangePicker, { type DateRangePickerProps } from '@cloudscape-design/components/date-range-picker';
import { useI18n } from '../i18n/useI18n';

export interface LocalizedDateRangePickerProps {
  value: DateRangePickerProps.Value | null;
  onChange: (value: DateRangePickerProps.Value | null) => void;
  placeholder?: string;
  relativeOptions?: DateRangePickerProps.RelativeOption[];
  i18nStrings?: DateRangePickerProps.I18nStrings;
}

export const DEFAULT_DATE_RANGE: DateRangePickerProps.Value = {
  type: 'relative',
  amount: 30,
  unit: 'day',
};

const DEFAULT_RELATIVE_OPTIONS: DateRangePickerProps.RelativeOption[] = [
  { key: '7d', amount: 7, unit: 'day', type: 'relative' },
  { key: '30d', amount: 30, unit: 'day', type: 'relative' },
  { key: '90d', amount: 90, unit: 'day', type: 'relative' },
];

export function useLocalizedDateRangeI18nStrings(): DateRangePickerProps.I18nStrings {
  const { t } = useI18n();

  const unitSingular = (unit: string): string => {
    switch (unit) {
      case 'day': return t('dateRangePicker.unit.day.singular');
      case 'week': return t('dateRangePicker.unit.week.singular');
      case 'month': return t('dateRangePicker.unit.month.singular');
      case 'year': return t('dateRangePicker.unit.year.singular');
      default: return unit;
    }
  };

  const unitPlural = (unit: string): string => {
    switch (unit) {
      case 'day': return t('dateRangePicker.unit.day.plural');
      case 'week': return t('dateRangePicker.unit.week.plural');
      case 'month': return t('dateRangePicker.unit.month.plural');
      case 'year': return t('dateRangePicker.unit.year.plural');
      default: return unit;
    }
  };

  return {
    todayAriaLabel: t('dateRangePicker.today'),
    nextMonthAriaLabel: t('dateRangePicker.nextMonth'),
    previousMonthAriaLabel: t('dateRangePicker.previousMonth'),
    customRelativeRangeDurationLabel: t('dateRangePicker.duration'),
    customRelativeRangeDurationPlaceholder: t('dateRangePicker.duration'),
    customRelativeRangeOptionLabel: t('dateRangePicker.custom.label'),
    customRelativeRangeOptionDescription: t('dateRangePicker.custom.description'),
    customRelativeRangeUnitLabel: t('dateRangePicker.unit.label'),
    relativeModeTitle: t('dateRangePicker.mode.relative'),
    absoluteModeTitle: t('dateRangePicker.mode.absolute'),
    relativeRangeSelectionHeading: t('dateRangePicker.relativeHeading'),
    startDateLabel: t('dateRangePicker.startDate'),
    startTimeLabel: t('dateRangePicker.startTime'),
    endDateLabel: t('dateRangePicker.endDate'),
    endTimeLabel: t('dateRangePicker.endTime'),
    dateTimeConstraintText: '',
    clearButtonLabel: t('common.clear'),
    cancelButtonLabel: t('common.cancel'),
    applyButtonLabel: t('common.apply'),
    formatRelativeRange: (v) => t('dateRangePicker.lastN', { amount: v.amount, unit: unitPlural(v.unit) }),
    formatUnit: (unit, value) => (value === 1 ? unitSingular(unit) : unitPlural(unit)),
    renderSelectedAbsoluteRangeAriaLive: (startDate, endDate) =>
      t('dateRangePicker.selectedRange', { start: startDate, end: endDate }),
  };
}

export function useIsValidRange(): (
  range: DateRangePickerProps.Value | null,
) => DateRangePickerProps.ValidationResult {
  const { t } = useI18n();
  return (range) => {
    if (range?.type === 'absolute') {
      if (!range.startDate || !range.endDate) {
        return { valid: false, errorMessage: t('dateRangePicker.error.missingDates') };
      }
      if (range.startDate > range.endDate) {
        return { valid: false, errorMessage: t('dateRangePicker.error.startAfterEnd') };
      }
    }
    return { valid: true };
  };
}

// Backwards-compatible export for tests referencing isValidRange.
export function isValidRange(
  range: DateRangePickerProps.Value | null,
): DateRangePickerProps.ValidationResult {
  if (range?.type === 'absolute') {
    if (!range.startDate || !range.endDate) {
      return { valid: false, errorMessage: 'Select both dates' };
    }
    if (range.startDate > range.endDate) {
      return { valid: false, errorMessage: 'Start date must be before end date' };
    }
  }
  return { valid: true };
}

export default function LocalizedDateRangePicker({
  value,
  onChange,
  placeholder,
  relativeOptions = DEFAULT_RELATIVE_OPTIONS,
  i18nStrings,
}: LocalizedDateRangePickerProps) {
  const { t, locale } = useI18n();
  const localizedI18nStrings = useLocalizedDateRangeI18nStrings();
  const validate = useIsValidRange();

  return (
    <DateRangePicker
      value={value}
      onChange={({ detail }) => onChange(detail.value)}
      placeholder={placeholder ?? t('dateRangePicker.placeholder')}
      relativeOptions={relativeOptions}
      i18nStrings={i18nStrings ?? localizedI18nStrings}
      isValidRange={validate}
      locale={locale}
    />
  );
}
