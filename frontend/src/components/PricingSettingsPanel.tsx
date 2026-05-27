import { useState, useEffect, useCallback } from 'react';
import Form from '@cloudscape-design/components/form';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Button from '@cloudscape-design/components/button';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Flashbar, { type FlashbarProps } from '@cloudscape-design/components/flashbar';
import Box from '@cloudscape-design/components/box';
import { get, put, ApiError } from '../api/client';
import { useI18n } from '../i18n/useI18n';
import SkeletonLoader from './SkeletonLoader';
import type { TierPricingResponse } from '../types';

interface TierFormEntry {
  name: string;
  monthlyPrice: string;
  includedCredits: string;
}

interface ValidationErrors {
  tiers: Record<number, { name?: string; monthlyPrice?: string; includedCredits?: string }>;
  overageRate?: string;
  general?: string;
}

export default function PricingSettingsPanel() {
  const { t } = useI18n();

  const [tiers, setTiers] = useState<TierFormEntry[]>([]);
  const [overageRate, setOverageRate] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<ValidationErrors>({ tiers: {} });
  const [flashItems, setFlashItems] = useState<FlashbarProps.MessageDefinition[]>([]);
  const [notConfigured, setNotConfigured] = useState(false);

  const fetchConfig = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await get<TierPricingResponse>('/api/config/tier-pricing');
      if (resp.status === 'not_configured' || !resp.config) {
        setNotConfigured(true);
        setTiers([]);
        setOverageRate('');
      } else {
        setNotConfigured(false);
        const tierEntries = Object.entries(resp.config.tiers).map(([name, entry]) => ({
          name,
          monthlyPrice: String(entry.monthlyPrice),
          includedCredits: String(entry.includedCredits),
        }));
        setTiers(tierEntries);
        setOverageRate(String(resp.config.overagePricePerCredit));
      }
    } catch {
      setNotConfigured(true);
      setTiers([]);
      setOverageRate('');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchConfig();
  }, [fetchConfig]);

  const validate = (): boolean => {
    const newErrors: ValidationErrors = { tiers: {} };
    let valid = true;

    if (tiers.length < 2) {
      newErrors.general = t('tierPricing.validation.minTiers');
      valid = false;
    }

    if (tiers.length > 10) {
      newErrors.general = t('tierPricing.validation.maxTiers');
      valid = false;
    }

    tiers.forEach((tier, index) => {
      const tierErrors: { name?: string; monthlyPrice?: string; includedCredits?: string } = {};

      if (!tier.name.trim()) {
        tierErrors.name = t('tierPricing.validation.nameRequired');
        valid = false;
      }

      const price = parseFloat(tier.monthlyPrice);
      if (isNaN(price) || price < 0) {
        tierErrors.monthlyPrice = t('tierPricing.validation.priceNonNegative');
        valid = false;
      }

      const credits = parseFloat(tier.includedCredits);
      if (isNaN(credits) || credits <= 0 || !Number.isInteger(credits)) {
        tierErrors.includedCredits = t('tierPricing.validation.creditsPositive');
        valid = false;
      }

      if (Object.keys(tierErrors).length > 0) {
        newErrors.tiers[index] = tierErrors;
      }
    });

    // Check ascending price order
    for (let i = 1; i < tiers.length; i++) {
      const prevPrice = parseFloat(tiers[i - 1].monthlyPrice);
      const currPrice = parseFloat(tiers[i].monthlyPrice);
      if (!isNaN(prevPrice) && !isNaN(currPrice) && currPrice <= prevPrice) {
        if (!newErrors.tiers[i]) newErrors.tiers[i] = {};
        newErrors.tiers[i].monthlyPrice = t('tierPricing.validation.ascendingPrices');
        valid = false;
      }
    }

    const rate = parseFloat(overageRate);
    if (isNaN(rate) || rate <= 0) {
      newErrors.overageRate = t('tierPricing.validation.overagePositive');
      valid = false;
    }

    setErrors(newErrors);
    return valid;
  };

  const handleSubmit = async () => {
    if (!validate()) return;

    setSaving(true);
    setFlashItems([]);

    const tiersPayload: Record<string, { monthlyPrice: number; includedCredits: number }> = {};
    for (const tier of tiers) {
      tiersPayload[tier.name.trim()] = {
        monthlyPrice: parseFloat(tier.monthlyPrice),
        includedCredits: parseInt(tier.includedCredits, 10),
      };
    }

    try {
      await put<{ status: string; message: string }>('/api/config/tier-pricing', {
        tiers: tiersPayload,
        overagePricePerCredit: parseFloat(overageRate),
      });
      setNotConfigured(false);
      setFlashItems([
        {
          type: 'success',
          content: t('tierPricing.success'),
          dismissible: true,
          onDismiss: () => setFlashItems([]),
          id: 'pricing-save-success',
        },
      ]);
      setErrors({ tiers: {} });
    } catch (err) {
      if (err instanceof ApiError) {
        setErrors((prev) => ({ ...prev, general: err.message }));
      } else {
        setErrors((prev) => ({
          ...prev,
          general: t('tierPricing.error'),
        }));
      }
    } finally {
      setSaving(false);
    }
  };

  const addTier = () => {
    if (tiers.length >= 10) return;
    setTiers([...tiers, { name: '', monthlyPrice: '', includedCredits: '' }]);
  };

  const removeTier = (index: number) => {
    if (tiers.length <= 2) return;
    setTiers(tiers.filter((_, i) => i !== index));
  };

  const updateTier = (index: number, field: keyof TierFormEntry, value: string) => {
    const updated = [...tiers];
    updated[index] = { ...updated[index], [field]: value };
    setTiers(updated);
  };

  if (loading) {
    return (
      <Container header={<Header variant="h2">{t('tierPricing.title')}</Header>}>
        <SkeletonLoader variant="container" />
      </Container>
    );
  }

  if (notConfigured && tiers.length === 0) {
    return (
      <Container
        header={
          <Header variant="h2" description={t('tierPricing.description')}>
            {t('tierPricing.title')}
          </Header>
        }
      >
        <SpaceBetween size="m">
          <Box textAlign="center" padding={{ vertical: 'l' }}>
            <SpaceBetween size="s">
              <Box variant="p">{t('tierPricing.empty')}</Box>
              <Button
                onClick={() => {
                  setTiers([
                    { name: 'PRO', monthlyPrice: '20', includedCredits: '1000' },
                    { name: 'PRO_PLUS', monthlyPrice: '40', includedCredits: '2000' },
                    { name: 'POWER', monthlyPrice: '200', includedCredits: '10000' },
                  ]);
                  setOverageRate('0.04');
                  setNotConfigured(false);
                }}
              >
                {t('tierPricing.addTier')}
              </Button>
            </SpaceBetween>
          </Box>
        </SpaceBetween>
      </Container>
    );
  }

  return (
    <Container
      header={
        <Header variant="h2" description={t('tierPricing.description')}>
          {t('tierPricing.title')}
        </Header>
      }
    >
      <Flashbar items={flashItems} />
      <Form
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="primary" onClick={handleSubmit} loading={saving}>
              {saving ? t('tierPricing.saving') : t('tierPricing.save')}
            </Button>
          </SpaceBetween>
        }
        errorText={errors.general}
      >
        <SpaceBetween size="l">
          {tiers.map((tier, index) => (
            <Container
              key={index}
              header={
                <Header
                  variant="h3"
                  actions={
                    tiers.length > 2 ? (
                      <Button onClick={() => removeTier(index)} variant="icon" iconName="close">
                        {t('tierPricing.removeTier')}
                      </Button>
                    ) : undefined
                  }
                >
                  {t('tierPricing.tier.name')} {index + 1}
                </Header>
              }
            >
              <SpaceBetween size="m">
                <FormField
                  label={t('tierPricing.tier.name')}
                  errorText={errors.tiers[index]?.name}
                >
                  <Input
                    value={tier.name}
                    onChange={({ detail }) => updateTier(index, 'name', detail.value)}
                    placeholder="e.g. PRO"
                  />
                </FormField>
                <FormField
                  label={t('tierPricing.tier.monthlyPrice')}
                  errorText={errors.tiers[index]?.monthlyPrice}
                >
                  <Input
                    value={tier.monthlyPrice}
                    onChange={({ detail }) => updateTier(index, 'monthlyPrice', detail.value)}
                    type="number"
                    inputMode="decimal"
                  />
                </FormField>
                <FormField
                  label={t('tierPricing.tier.includedCredits')}
                  errorText={errors.tiers[index]?.includedCredits}
                >
                  <Input
                    value={tier.includedCredits}
                    onChange={({ detail }) => updateTier(index, 'includedCredits', detail.value)}
                    type="number"
                    inputMode="numeric"
                  />
                </FormField>
              </SpaceBetween>
            </Container>
          ))}

          {tiers.length < 10 && (
            <Button onClick={addTier} iconName="add-plus">
              {t('tierPricing.addTier')}
            </Button>
          )}

          <FormField
            label={t('tierPricing.overageRate')}
            errorText={errors.overageRate}
          >
            <Input
              value={overageRate}
              onChange={({ detail }) => setOverageRate(detail.value)}
              type="number"
              inputMode="decimal"
            />
          </FormField>
        </SpaceBetween>
      </Form>
    </Container>
  );
}
