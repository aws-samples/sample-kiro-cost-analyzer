import Badge from '@cloudscape-design/components/badge';
import { useI18n } from '../i18n/useI18n';
import type { TierRecommendation } from '../types';

interface TierBadgeProps {
  recommendation: TierRecommendation | null;
  onClick: () => void;
}

export default function TierBadge({ recommendation, onClick }: TierBadgeProps) {
  const { t } = useI18n();

  if (!recommendation) {
    return null;
  }

  const isUpgrade = recommendation.recommendationType === 'upgrade';
  const label = isUpgrade
    ? t('recommendations.badge.upgrade')
    : t('recommendations.badge.downgrade');
  const color = isUpgrade ? 'blue' : 'grey';

  return (
    <span onClick={onClick} style={{ cursor: 'pointer' }}>
      <Badge color={color}>{label}</Badge>
    </span>
  );
}
