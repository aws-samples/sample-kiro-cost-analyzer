const BASE_URL = import.meta.env.VITE_API_URL as string | undefined;

function getToken(): string | null {
  return localStorage.getItem('kiro_id_token');
}

function handleUnauthorized() {
  localStorage.removeItem('kiro_id_token');
  localStorage.removeItem('kiro_access_token');
  localStorage.removeItem('kiro_refresh_token');
  localStorage.removeItem('kiro_token_expiry');
  window.location.href = '/';
}

export class ApiError extends Error {
  status: number;
  body: string;

  constructor(status: number, body: string) {
    const message =
      status >= 500
        ? 'Erro interno do servidor. Tente novamente mais tarde.'
        : body || `Erro na requisição (${status})`;
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
  }

  get isServerError(): boolean {
    return this.status >= 500;
  }

  get isClientError(): boolean {
    return this.status >= 400 && this.status < 500;
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const url = BASE_URL ? `${BASE_URL}${path}` : path;

  const res = await fetch(url, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });

  if (res.status === 401) {
    handleUnauthorized();
    throw new ApiError(401, 'Sessão expirada. Redirecionando para login...');
  }

  if (!res.ok) {
    // Only the API's own `message` field (a safe, English, machine-authored
    // string per the backend's response contract) is used as the error
    // body. The raw response text is never used as a fallback — an
    // unparseable body could be an HTML error page from an intermediary
    // (API Gateway/CloudFront) or, in a backend bug scenario, an echo of
    // request-supplied data, neither of which should be surfaced verbatim.
    const text = await res.text();
    let apiMessage = `Erro na requisição (${res.status})`;
    try {
      const parsed = JSON.parse(text);
      if (typeof parsed.message === 'string' && parsed.message) {
        apiMessage = parsed.message;
      }
    } catch {
      // Not JSON — keep the generic fallback above.
    }
    throw new ApiError(res.status, apiMessage);
  }

  const contentType = res.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    return res.json() as Promise<T>;
  }
  return res.text() as Promise<T>;
}

export function get<T>(path: string, params?: Record<string, string>): Promise<T> {
  const query = params ? '?' + new URLSearchParams(params).toString() : '';
  return request<T>('GET', `${path}${query}`);
}

export function post<T>(path: string, body?: unknown): Promise<T> {
  return request<T>('POST', path, body);
}

export function put<T>(path: string, body?: unknown): Promise<T> {
  return request<T>('PUT', path, body);
}

export function del<T>(path: string): Promise<T> {
  return request<T>('DELETE', path);
}
