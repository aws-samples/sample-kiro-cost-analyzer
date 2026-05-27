import { useEffect, useState, useCallback } from 'react';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Table from '@cloudscape-design/components/table';
import Button from '@cloudscape-design/components/button';
import Alert from '@cloudscape-design/components/alert';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import Modal from '@cloudscape-design/components/modal';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Select from '@cloudscape-design/components/select';
import Autosuggest from '@cloudscape-design/components/autosuggest';
import Box from '@cloudscape-design/components/box';
import Badge from '@cloudscape-design/components/badge';
import { get, post, put, del } from '../api/client';
import { useAuth } from '../auth/useAuth';
import { useI18n } from '../i18n/useI18n';
import type { CognitoUser } from '../types';

interface KiroUser {
  userId: string;
  displayName: string;
  userName: string;
}

interface CognitoUserWithRole extends CognitoUser {
  isAdmin?: boolean;
  kiroUserId?: string;
}

export default function UsersPage() {
  const { user: currentUser } = useAuth();
  const { t, formatDateTime } = useI18n();
  const [users, setUsers] = useState<CognitoUserWithRole[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // Add user modal
  const [addVisible, setAddVisible] = useState(false);
  const [newEmail, setNewEmail] = useState('');
  const [newKiroUserId, setNewKiroUserId] = useState('');
  const [newRole, setNewRole] = useState<'user' | 'admin'>('user');
  const [adding, setAdding] = useState(false);

  // Kiro users for autocomplete
  const [kiroUsers, setKiroUsers] = useState<KiroUser[]>([]);
  const [kiroUsersLoaded, setKiroUsersLoaded] = useState(false);

  // Delete confirmation modal
  const [deleteTarget, setDeleteTarget] = useState<CognitoUserWithRole | null>(null);
  const [deleting, setDeleting] = useState(false);

  // Toggle role loading state
  const [togglingRole, setTogglingRole] = useState<string | null>(null);

  const fetchUsers = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await get<{ users: CognitoUserWithRole[] }>('/api/users');
      setUsers(resp.users ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('users.error.load'));
    } finally {
      setLoading(false);
    }
  }, [t]);

  // Fetch Kiro users for autocomplete and table display
  const fetchKiroUsers = useCallback(async () => {
    if (kiroUsersLoaded) return;
    try {
      const resp = await get<{ users: KiroUser[] }>('/api/kiro-users');
      setKiroUsers(resp.users ?? []);
      setKiroUsersLoaded(true);
    } catch {
      // silently fail — user can still type manually
    }
  }, [kiroUsersLoaded]);

  useEffect(() => {
    fetchUsers();
    fetchKiroUsers();
  }, [fetchUsers, fetchKiroUsers]);

  const handleOpenAddModal = useCallback(() => {
    setAddVisible(true);
    fetchKiroUsers();
  }, [fetchKiroUsers]);

  const kiroUserOptions = kiroUsers
    .filter((ku) => {
      if (!newKiroUserId) return true;
      const q = newKiroUserId.toLowerCase();
      return (
        ku.displayName.toLowerCase().includes(q) ||
        ku.userName.toLowerCase().includes(q) ||
        ku.userId.toLowerCase().includes(q)
      );
    })
    .map((ku) => ({
      value: ku.userId,
      label: ku.displayName || ku.userName,
      description: `${ku.userName} — ${ku.userId.slice(0, 12)}…`,
    }));

  const handleAddUser = async () => {
    const email = newEmail.trim();
    if (!email) {
      setError(t('users.error.emailRequired'));
      return;
    }
    setAdding(true);
    setError(null);
    setSuccess(null);
    try {
      const resp = await post<{ status: string; message?: string }>('/api/users', {
        email,
        role: newRole,
        kiroUserId: newKiroUserId.trim() || undefined,
      });
      if (resp.status === 'error') {
        setError(resp.message ?? t('users.error.create'));
      } else {
        setSuccess(t('users.success.created', { email }));
        setAddVisible(false);
        setNewEmail('');
        setNewKiroUserId('');
        setNewRole('user');
        fetchUsers();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t('users.error.create'));
    } finally {
      setAdding(false);
    }
  };

  const handleToggleRole = async (user: CognitoUserWithRole) => {
    const newIsAdmin = !user.isAdmin;
    setTogglingRole(user.username);
    setError(null);
    setSuccess(null);
    try {
      const resp = await put<{ status: string; message?: string }>(
        `/api/users/${user.username}`,
        { isAdmin: newIsAdmin },
      );
      if (resp.status === 'error') {
        setError(resp.message ?? t('users.error.changeRole'));
      } else {
        setSuccess(t('users.success.roleChanged', {
          email: user.email,
          role: newIsAdmin ? t('users.role.admin') : t('users.role.standard'),
        }));
        fetchUsers();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t('users.error.changeRole'));
    } finally {
      setTogglingRole(null);
    }
  };

  const handleDeleteUser = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    setError(null);
    setSuccess(null);
    try {
      const resp = await del<{ status: string; message?: string }>(`/api/users/${deleteTarget.username}`);
      if (resp.status === 'error') {
        setError(resp.message ?? t('users.error.delete'));
      } else {
        setSuccess(t('users.success.deleted', { email: deleteTarget.email }));
        fetchUsers();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t('users.error.delete'));
    } finally {
      setDeleting(false);
      setDeleteTarget(null);
    }
  };

  const isSelf = (u: CognitoUserWithRole) => {
    const currentSub = currentUser?.sub ?? '';
    const currentEmail = currentUser?.email ?? '';
    return u.username === currentSub || u.email === currentEmail;
  };

  return (
    <SpaceBetween size="l">
      {error && (
        <Alert type="error" dismissible onDismiss={() => setError(null)}>
          {error}
        </Alert>
      )}
      {success && (
        <Alert type="success" dismissible onDismiss={() => setSuccess(null)}>
          {success}
        </Alert>
      )}

      <Table
        header={
          <Header
            actions={
              <Button variant="primary" onClick={handleOpenAddModal}>
                {t('users.action.add')}
              </Button>
            }
            counter={`(${users.length})`}
          >
            {t('users.table.title')}
          </Header>
        }
        items={users}
        loading={loading}
        loadingText={t('users.table.loading')}
        empty={
          <Box textAlign="center" color="text-body-secondary" padding="l">
            {t('users.table.empty')}
          </Box>
        }
        columnDefinitions={[
          {
            id: 'email',
            header: t('users.table.header.email'),
            cell: (item) => (
              <SpaceBetween size="xs" direction="horizontal">
                <span>{item.email}</span>
                {isSelf(item) && <Badge color="blue">{t('users.table.you')}</Badge>}
              </SpaceBetween>
            ),
            sortingField: 'email',
          },
          {
            id: 'kiroUserId',
            header: t('users.table.header.kiroUserId'),
            cell: (item) => {
              const kiroId = (item as CognitoUserWithRole).kiroUserId;
              if (!kiroId) return '—';
              const matched = kiroUsers.find((ku) => ku.userId === kiroId);
              if (matched) {
                return <span title={kiroId}>{matched.displayName || matched.userName}</span>;
              }
              return <span title={kiroId}>{kiroId.slice(0, 12)}…</span>;
            },
          },
          {
            id: 'role',
            header: t('users.table.header.role'),
            cell: (item) => (
              <Badge color={item.isAdmin ? 'red' : 'grey'}>
                {item.isAdmin ? t('users.role.adminShort') : t('users.role.standard')}
              </Badge>
            ),
          },
          {
            id: 'status',
            header: t('users.table.header.status'),
            cell: (item) => {
              const type = item.status === 'CONFIRMED' ? 'success'
                : item.status === 'FORCE_CHANGE_PASSWORD' ? 'warning'
                : 'info';
              return <StatusIndicator type={type}>{item.status}</StatusIndicator>;
            },
          },
          {
            id: 'createdAt',
            header: t('users.table.header.createdAt'),
            cell: (item) => {
              try {
                return formatDateTime(item.createdAt);
              } catch {
                return item.createdAt;
              }
            },
          },
          {
            id: 'actions',
            header: t('users.table.header.actions'),
            cell: (item) => (
              <SpaceBetween size="xs" direction="horizontal">
                <Button
                  variant="inline-link"
                  onClick={() => handleToggleRole(item)}
                  disabled={isSelf(item) || togglingRole === item.username}
                  loading={togglingRole === item.username}
                >
                  {item.isAdmin ? t('users.action.makeStandard') : t('users.action.makeAdmin')}
                </Button>
                <Button
                  variant="inline-link"
                  onClick={() => setDeleteTarget(item)}
                  disabled={isSelf(item)}
                >
                  {t('users.action.delete')}
                </Button>
              </SpaceBetween>
            ),
          },
        ]}
        sortingDisabled
      />

      {/* Add User Modal */}
      <Modal
        visible={addVisible}
        onDismiss={() => { setAddVisible(false); setNewEmail(''); setNewKiroUserId(''); setNewRole('user'); }}
        header={t('users.addModal.title')}
        footer={
          <Box float="right">
            <SpaceBetween size="xs" direction="horizontal">
              <Button variant="link" onClick={() => { setAddVisible(false); setNewEmail(''); setNewKiroUserId(''); setNewRole('user'); }}>
                {t('common.cancel')}
              </Button>
              <Button variant="primary" onClick={handleAddUser} loading={adding}>
                {t('users.addModal.submit')}
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <FormField label={t('login.email')} description={t('users.addModal.emailDescription')}>
            <Input
              value={newEmail}
              onChange={({ detail }) => setNewEmail(detail.value)}
              placeholder={t('users.addModal.emailPlaceholder')}
              type="email"
            />
          </FormField>
          <FormField label={t('users.addModal.kiroUserId')} description={t('users.addModal.kiroUserIdDescription')}>
            <Autosuggest
              value={newKiroUserId}
              onChange={({ detail }) => setNewKiroUserId(detail.value)}
              options={kiroUserOptions}
              placeholder={t('users.addModal.kiroUserIdPlaceholder')}
              enteredTextLabel={(value) => value}
              empty={t('users.addModal.kiroUserIdEmpty')}
              filteringType="manual"
            />
          </FormField>
          <FormField label={t('users.addModal.userType')}>
            <Select
              selectedOption={{ value: newRole, label: newRole === 'admin' ? t('users.role.admin') : t('users.role.standard') }}
              onChange={({ detail }) => setNewRole(detail.selectedOption.value as 'user' | 'admin')}
              options={[
                { value: 'user', label: t('users.role.standard'), description: t('users.role.standardDescription') },
                { value: 'admin', label: t('users.role.admin'), description: t('users.role.adminDescription') },
              ]}
            />
          </FormField>
        </SpaceBetween>
      </Modal>

      {/* Delete Confirmation Modal */}
      <Modal
        visible={deleteTarget !== null}
        onDismiss={() => setDeleteTarget(null)}
        header={t('users.deleteModal.title')}
        footer={
          <Box float="right">
            <SpaceBetween size="xs" direction="horizontal">
              <Button variant="link" onClick={() => setDeleteTarget(null)}>
                {t('common.cancel')}
              </Button>
              <Button variant="primary" onClick={handleDeleteUser} loading={deleting}>
                {t('users.deleteModal.submit')}
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <Alert type="warning">
            {t('users.deleteModal.warning')}
          </Alert>
          <Box>
            {t('users.deleteModal.confirm')} <strong>{deleteTarget?.email}</strong>?
          </Box>
        </SpaceBetween>
      </Modal>
    </SpaceBetween>
  );
}
