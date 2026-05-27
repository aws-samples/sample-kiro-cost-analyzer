import { createContext, useEffect, useState, useCallback, type ReactNode } from 'react';
import {
  CognitoUserPool,
  CognitoUser,
  AuthenticationDetails,
  CognitoUserSession,
  CognitoRefreshToken,
} from 'amazon-cognito-identity-js';

export interface AuthUser {
  sub: string;
  email: string;
  groups: string[];
  [key: string]: unknown;
}

export interface AuthContextValue {
  isAuthenticated: boolean;
  user: AuthUser | null;
  idToken: string | null;
  loading: boolean;
  newPasswordRequired: boolean;
  newPasswordEmail: string | null;
  login: (email: string, password: string) => Promise<void>;
  completeNewPassword: (newPassword: string) => Promise<void>;
  signup: (email: string, password: string) => Promise<void>;
  confirmSignup: (email: string, code: string) => Promise<void>;
  forgotPassword: (email: string) => Promise<void>;
  resetPassword: (email: string, code: string, newPassword: string) => Promise<void>;
  logout: () => void;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

const USER_POOL_ID = import.meta.env.VITE_COGNITO_USER_POOL_ID as string;
const CLIENT_ID = import.meta.env.VITE_COGNITO_CLIENT_ID as string;

const userPool = new CognitoUserPool({
  UserPoolId: USER_POOL_ID,
  ClientId: CLIENT_ID,
});

const TOKEN_KEYS = {
  idToken: 'kiro_id_token',
  accessToken: 'kiro_access_token',
  refreshToken: 'kiro_refresh_token',
  expiry: 'kiro_token_expiry',
} as const;

export function decodeJwtPayload(token: string): Record<string, unknown> {
  const payload = token.split('.')[1];
  const base64 = payload.replace(/-/g, '+').replace(/_/g, '/');
  const json = decodeURIComponent(
    atob(base64)
      .split('')
      .map((c) => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2))
      .join('')
  );
  return JSON.parse(json);
}

export function parseUser(idToken: string): AuthUser {
  const claims = decodeJwtPayload(idToken);
  return {
    sub: claims.sub as string,
    email: (claims.email as string) ?? '',
    groups: (claims['cognito:groups'] as string[]) ?? [],
    ...claims,
  };
}

function isTokenExpired(): boolean {
  const expiry = localStorage.getItem(TOKEN_KEYS.expiry);
  if (!expiry) return true;
  return Date.now() > Number(expiry);
}

function storeTokens(session: CognitoUserSession) {
  const idToken = session.getIdToken().getJwtToken();
  const accessToken = session.getAccessToken().getJwtToken();
  const refreshToken = session.getRefreshToken().getToken();
  const expiresIn = session.getIdToken().getExpiration() - Math.floor(Date.now() / 1000);

  localStorage.setItem(TOKEN_KEYS.idToken, idToken);
  localStorage.setItem(TOKEN_KEYS.accessToken, accessToken);
  localStorage.setItem(TOKEN_KEYS.refreshToken, refreshToken);
  localStorage.setItem(TOKEN_KEYS.expiry, String(Date.now() + expiresIn * 1000));
}

function clearTokens() {
  localStorage.removeItem(TOKEN_KEYS.idToken);
  localStorage.removeItem(TOKEN_KEYS.accessToken);
  localStorage.removeItem(TOKEN_KEYS.refreshToken);
  localStorage.removeItem(TOKEN_KEYS.expiry);
}

/**
 * Detect external storage manipulation (e.g., another tab injecting tokens).
 * If a token key is modified externally and doesn't match a valid JWT structure,
 * clear all tokens as a precaution.
 */
function setupStorageGuard(onTamper: () => void) {
  window.addEventListener('storage', (event) => {
    if (event.key && Object.values(TOKEN_KEYS).includes(event.key as typeof TOKEN_KEYS[keyof typeof TOKEN_KEYS])) {
      // If token was set from another context (XSS in another tab), force logout
      if (event.key === TOKEN_KEYS.idToken && event.newValue) {
        const parts = event.newValue.split('.');
        if (parts.length !== 3) {
          clearTokens();
          onTamper();
        }
      }
    }
  });
}

function getCognitoUser(email: string): CognitoUser {
  return new CognitoUser({
    Username: email,
    Pool: userPool,
  });
}

function refreshSession(cognitoUser: CognitoUser, refreshToken: string): Promise<CognitoUserSession> {
  return new Promise((resolve, reject) => {
    const token = new CognitoRefreshToken({ RefreshToken: refreshToken });
    cognitoUser.refreshSession(token, (err, session) => {
      if (err) {
        reject(err);
      } else {
        resolve(session as CognitoUserSession);
      }
    });
  });
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [idToken, setIdToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [newPasswordRequired, setNewPasswordRequired] = useState(false);
  const [newPasswordEmail, setNewPasswordEmail] = useState<string | null>(null);
  const [pendingCognitoUser, setPendingCognitoUser] = useState<CognitoUser | null>(null);
  const [pendingUserAttributes, setPendingUserAttributes] = useState<Record<string, string>>({});

  const login = useCallback(async (email: string, password: string): Promise<void> => {
    const cognitoUser = getCognitoUser(email);
    const authDetails = new AuthenticationDetails({
      Username: email,
      Password: password,
    });

    return new Promise<void>((resolve, reject) => {
      cognitoUser.authenticateUser(authDetails, {
        onSuccess: (session: CognitoUserSession) => {
          storeTokens(session);
          const token = session.getIdToken().getJwtToken();
          setIdToken(token);
          setUser(parseUser(token));
          setNewPasswordRequired(false);
          setNewPasswordEmail(null);
          resolve();
        },
        onFailure: (err: Error) => {
          reject(err);
        },
        newPasswordRequired: (userAttributes: Record<string, string>) => {
          // Remove non-writable attributes that Cognito returns
          delete userAttributes.email_verified;
          delete userAttributes.email;
          setPendingCognitoUser(cognitoUser);
          setPendingUserAttributes(userAttributes);
          setNewPasswordRequired(true);
          setNewPasswordEmail(email);
          resolve();
        },
      });
    });
  }, []);

  const completeNewPassword = useCallback(async (newPassword: string): Promise<void> => {
    if (!pendingCognitoUser) {
      throw new Error('No pending password change');
    }
    return new Promise<void>((resolve, reject) => {
      pendingCognitoUser.completeNewPasswordChallenge(newPassword, pendingUserAttributes, {
        onSuccess: (session: CognitoUserSession) => {
          storeTokens(session);
          const token = session.getIdToken().getJwtToken();
          setIdToken(token);
          setUser(parseUser(token));
          setNewPasswordRequired(false);
          setNewPasswordEmail(null);
          setPendingCognitoUser(null);
          setPendingUserAttributes({});
          resolve();
        },
        onFailure: (err: Error) => {
          reject(err);
        },
      });
    });
  }, [pendingCognitoUser, pendingUserAttributes]);

  const signup = useCallback(async (email: string, password: string): Promise<void> => {
    return new Promise<void>((resolve, reject) => {
      userPool.signUp(email, password, [], [], (err) => {
        if (err) {
          reject(err);
        } else {
          resolve();
        }
      });
    });
  }, []);

  const confirmSignup = useCallback(async (email: string, code: string): Promise<void> => {
    const cognitoUser = getCognitoUser(email);
    return new Promise<void>((resolve, reject) => {
      cognitoUser.confirmRegistration(code, true, (err) => {
        if (err) {
          reject(err);
        } else {
          resolve();
        }
      });
    });
  }, []);

  const forgotPassword = useCallback(async (email: string): Promise<void> => {
    const cognitoUser = getCognitoUser(email);
    return new Promise<void>((resolve, reject) => {
      cognitoUser.forgotPassword({
        onSuccess: () => {
          resolve();
        },
        onFailure: (err: Error) => {
          reject(err);
        },
      });
    });
  }, []);

  const resetPassword = useCallback(async (email: string, code: string, newPassword: string): Promise<void> => {
    const cognitoUser = getCognitoUser(email);
    return new Promise<void>((resolve, reject) => {
      cognitoUser.confirmPassword(code, newPassword, {
        onSuccess: () => {
          resolve();
        },
        onFailure: (err: Error) => {
          reject(err);
        },
      });
    });
  }, []);

  const logout = useCallback(() => {
    // Invalidate all refresh tokens server-side (GlobalSignOut)
    const accessToken = localStorage.getItem(TOKEN_KEYS.accessToken);
    if (accessToken) {
      // Best-effort: revoke tokens server-side before clearing locally.
      // Uses the Cognito GlobalSignOut API directly with the access token.
      const region = (import.meta.env.VITE_COGNITO_USER_POOL_ID as string || '').split('_')[0];
      if (region) {
        fetch(`https://cognito-idp.${region}.amazonaws.com/`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/x-amz-json-1.1',
            'X-Amz-Target': 'AWSCognitoIdentityProviderService.GlobalSignOut',
          },
          body: JSON.stringify({ AccessToken: accessToken }),
        }).catch(() => { /* best-effort */ });
      }
    }
    clearTokens();
    setUser(null);
    setIdToken(null);
  }, []);

  useEffect(() => {
    let cancelled = false;

    // Guard against external token manipulation
    setupStorageGuard(() => {
      if (!cancelled) {
        setUser(null);
        setIdToken(null);
      }
    });

    async function init() {
      const storedIdToken = localStorage.getItem(TOKEN_KEYS.idToken);
      const storedRefreshToken = localStorage.getItem(TOKEN_KEYS.refreshToken);

      if (!storedIdToken) {
        setLoading(false);
        return;
      }

      if (!isTokenExpired()) {
        // Tokens are still valid — restore session
        if (!cancelled) {
          setIdToken(storedIdToken);
          setUser(parseUser(storedIdToken));
          setLoading(false);
        }
        return;
      }

      // Token is expired — try to refresh
      if (storedRefreshToken) {
        try {
          const claims = decodeJwtPayload(storedIdToken);
          const email = claims.email as string;
          if (email) {
            const cognitoUser = getCognitoUser(email);
            const session = await refreshSession(cognitoUser, storedRefreshToken);
            if (!cancelled) {
              storeTokens(session);
              const newToken = session.getIdToken().getJwtToken();
              setIdToken(newToken);
              setUser(parseUser(newToken));
            }
          } else {
            clearTokens();
          }
        } catch {
          clearTokens();
        }
      } else {
        clearTokens();
      }

      if (!cancelled) {
        setLoading(false);
      }
    }

    init();
    return () => { cancelled = true; };
  }, []);

  const isAuthenticated = user !== null && !isTokenExpired();

  return (
    <AuthContext.Provider
      value={{
        isAuthenticated,
        user,
        idToken,
        loading,
        newPasswordRequired,
        newPasswordEmail,
        login,
        completeNewPassword,
        signup,
        confirmSignup,
        forgotPassword,
        resetPassword,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}
