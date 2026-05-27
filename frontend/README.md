# Kiro Cost Analyzer — Frontend

Dashboard React com AWS Cloudscape para visualização de consumo do Kiro.

## Pré-requisitos

- Node.js 18+
- Backend deployado via SAM (ou `sam local start-api` para desenvolvimento local)

## Configuração

1. Copie o arquivo de variáveis de ambiente:

```bash
cp .env.example .env.local
```

2. Preencha os valores no `.env.local` com os outputs do deploy SAM:

| Variável | SAM Output | Descrição |
|----------|------------|-----------|
| `VITE_API_URL` | `ApiUrl` | URL do API Gateway (deixe vazio para usar proxy local) |
| `VITE_COGNITO_DOMAIN` | `CognitoDomain` | Domínio do Cognito Hosted UI (prefixe com `https://`) |
| `VITE_COGNITO_CLIENT_ID` | `UserPoolClientId` | Client ID do Cognito User Pool |
| `VITE_COGNITO_REDIRECT_URI` | — | URI de callback (`http://localhost:5173/callback` para dev) |

Para obter os outputs do SAM:

```bash
aws cloudformation describe-stacks --stack-name <STACK_NAME> --query "Stacks[0].Outputs"
```

## Desenvolvimento local

```bash
npm install
npm run dev
```

O servidor de desenvolvimento inicia em `http://localhost:5173`.

### Proxy de API

Quando `VITE_API_URL` não está definido, o frontend usa caminhos relativos (`/api/*`) que são redirecionados pelo proxy do Vite para `http://localhost:3001`. Para usar com `sam local start-api`:

```bash
# Terminal 1 — Backend local (porta 3000 por padrão do SAM)
sam local start-api

# Terminal 2 — Frontend
# Defina VITE_API_URL=http://localhost:3000 no .env.local
npm run dev
```

Quando `VITE_API_URL` está definido, o `api/client.ts` faz chamadas diretamente para a URL configurada (útil para apontar para o API Gateway deployado).

## Build para produção

```bash
npm run build
```

Os arquivos estáticos são gerados em `dist/` e podem ser hospedados no S3 + CloudFront.

## Autenticação

O frontend usa o fluxo PKCE (Authorization Code + PKCE) com o Cognito Hosted UI:

1. Usuário clica em "Entrar"
2. Redirect para Cognito Hosted UI
3. Após login, Cognito redireciona para `/callback` com authorization code
4. Frontend troca o code por tokens (id_token, access_token)
5. Tokens são armazenados no localStorage
6. Todas as chamadas à API incluem o id_token no header `Authorization: Bearer <token>`

O API Gateway valida o JWT automaticamente via Cognito Authorizer configurado no `template.yaml`.
