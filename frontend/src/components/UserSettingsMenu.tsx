/**
 * UserSettingsMenu — renders the gear-icon trigger that opens
 * `UserSettingsModal`, wired into `TopNavigation.utilities`.
 *
 * This component pairs the trigger (returned via `getUtility()`) with the
 * modal state (managed here). Call sites spread `getUtility()` into the
 * `utilities` array and render the component once in the tree — the
 * returned node hosts the modal.
 *
 * Rationale for this shape: `TopNavigation.utilities` only accepts a
 * restricted `button | menu-dropdown` shape, so the gear icon must be a
 * `type: 'button'` utility. The modal state cannot live inside a utility
 * object, so the component keeps it and the `utilities` array references
 * the exported trigger descriptor.
 */

import { useState } from 'react';
import type { TopNavigationProps } from '@cloudscape-design/components/top-navigation';
import { useI18n } from '../i18n/useI18n';
import UserSettingsModal from './UserSettingsModal';

/**
 * React component that renders ONLY the modal. The trigger is a utility
 * descriptor obtained from `useUserSettingsMenu()`.
 */
export interface UserSettingsMenuHandle {
  utility: TopNavigationProps.Utility;
  modalNode: React.ReactNode;
}

/**
 * Hook that returns `{ utility, modalNode }`. The utility is a button
 * shaped for `TopNavigation.utilities`; rendering `modalNode` somewhere in
 * the tree (typically as a sibling of the TopNavigation) attaches the
 * modal.
 */
export function useUserSettingsMenu(): UserSettingsMenuHandle {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);

  const utility: TopNavigationProps.Utility = {
    type: 'button',
    iconName: 'settings',
    ariaLabel: t('userSettings.openAriaLabel'),
    title: t('userSettings.openAriaLabel'),
    onClick: (event) => {
      event.preventDefault();
      setOpen(true);
    },
  };

  const modalNode = (
    <UserSettingsModal visible={open} onDismiss={() => setOpen(false)} />
  );

  return { utility, modalNode };
}
