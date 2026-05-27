# Plano de Implementação: Custom Auth + CloudFront

## Visão Geral

Este plano converte o design aprovado em tarefas incrementais de codificação. Cada tarefa constrói sobre as anteriores, começando pela infraestrutura (CloudFront, Cognito), passando pela refatoração do AuthProvider, criação das páginas de autenticação, atualização do roteamento, automação de deploy e finalizando com testes. A linguagem de implementação é TypeScript (React/Cloudscape) para o frontend e YAML (SAM/CloudFormation) para a infraestrutura.

## Tarefas

- [x] 1. Atualizar infraestrutura CloudFormation (template.yaml)
  - [x] 1.1 Adicionar distribuição CloudFront com OAC e bucket policy
    - Criar recurso `CloudFrontOAC` (AWS::CloudFront::OriginAccessControl) com `SigningProtocol: sigv4`, `SigningBehavior: always`, `OriginAccessControlOriginType: s3`
    - Criar recurso `CloudFrontDistribution` (AWS::CloudFront::Distribution) com:
      - Origem: `WebsiteBucket` via OAC (S3 REST API endpoint)
      - `ViewerProtocolPolicy: redirect-to-https`
      - `DefaultRootObject: index.html`
      - Custom Error Responses: 403 → `/index.html` (200), 404 → `/index.html` (200)
    - Criar recurso `WebsiteBucketPolicy` (AWS::S3::BucketPolicy) concedendo acesso de leitura ao CloudFront via principal OAC
    - _Requisitos: 6.1, 6.2, 6.3, 6.4, 7.1, 7.2_

  - [x] 1.2 Adicionar logging e monitoramento do CloudFront
    - Habilitar Standard Logging na distribuição CloudFront, gravando logs no `DataBucket` com prefixo `cloudfront-logs/`
    - Criar recurso `DataBucketLoggingPolicy` (AWS::S3::BucketPolicy) permitindo ao CloudFront gravar logs (principal `logging.s3.amazonaws.com`)
    - Criar recurso `CloudFrontMonitoring` (AWS::CloudFront::MonitoringSubscription) com `RealtimeMetricsSubscriptionConfig` habilitado
    - _Requisitos: 11.1, 11.2, 11.3_

  - [x] 1.3 Atualizar CognitoUserPoolClient para autenticação direta
    - Adicionar `ALLOW_USER_SRP_AUTH` e `ALLOW_USER_PASSWORD_AUTH` aos `ExplicitAuthFlows`
    - Manter `ALLOW_REFRESH_TOKEN_AUTH` e `GenerateSecret: false`
    - Adicionar URL do domínio CloudFront com path `/callback` às `CallbackURLs`
    - Adicionar URL do domínio CloudFront (raiz) às `LogoutURLs`
    - Manter URLs de `localhost:5173` para desenvolvimento local
    - _Requisitos: 4.1, 4.2, 4.3, 4.4, 8.1, 8.2, 8.3, 8.4_

  - [x] 1.4 Adicionar outputs do CloudFront no template
    - Adicionar output `CloudFrontDomainName` com o nome de domínio da distribuição
    - Adicionar output `CloudFrontDistributionId` com o ID da distribuição
    - _Requisitos: 9.1, 9.2_

- [x] 2. Checkpoint — Validar infraestrutura
  - Garantir que o template.yaml é válido executando `sam validate`
  - Verificar que todos os recursos novos estão corretamente referenciados
  - Perguntar ao usuário se há dúvidas antes de prosseguir

- [x] 3. Instalar dependências e configurar ambiente de testes no frontend
  - [x] 3.1 Instalar amazon-cognito-identity-js e dependências de teste
    - Executar `npm install amazon-cognito-identity-js` no diretório `frontend/`
    - Executar `npm install -D vitest @testing-library/react @testing-library/jest-dom @testing-library/user-event jsdom fast-check` no diretório `frontend/`
    - Adicionar script `"test": "vitest --run"` ao `package.json`
    - Criar arquivo de configuração do Vitest (`vitest.config.ts` ou seção em `vite.config.ts`) com `environment: 'jsdom'` e setup file
    - Criar arquivo de setup de testes (`src/test/setup.ts`) importando `@testing-library/jest-dom`
    - _Requisitos: 5.1 (dependência do SDK)_

  - [x] 3.2 Atualizar variáveis de ambiente
    - Atualizar `frontend/.env.example` removendo `VITE_COGNITO_DOMAIN` e `VITE_COGNITO_REDIRECT_URI`, adicionando `VITE_COGNITO_USER_POOL_ID`
    - Atualizar `frontend/.env.local` com a nova variável `VITE_COGNITO_USER_POOL_ID` e remover variáveis obsoletas
    - _Requisitos: 5.1 (configuração do SDK)_

- [x] 4. Refatorar AuthProvider para autenticação direta via Cognito
  - [x] 4.1 Reescrever AuthProvider.tsx usando amazon-cognito-identity-js
    - Remover todo o fluxo PKCE/redirect (funções `generateRandomString`, `generateCodeChallenge`, `exchangeCodeForTokens`)
    - Configurar `CognitoUserPool` com `UserPoolId` e `ClientId` das variáveis de ambiente
    - Implementar função `login(email, password)` usando `authenticateUser` com SRP
    - Implementar função `signup(email, password)` usando `signUp`
    - Implementar função `confirmSignup(email, code)` usando `confirmRegistration`
    - Implementar função `forgotPassword(email)` usando `forgotPassword`
    - Implementar função `resetPassword(email, code, newPassword)` usando `confirmPassword`
    - Implementar função `logout()` que limpa tokens do localStorage e reseta estado (sem redirect externo)
    - Implementar renovação automática de tokens via `refreshSession` quando o id_token estiver expirado
    - Atualizar a interface `AuthContextValue` para expor todas as novas funções
    - Manter armazenamento de tokens com as mesmas chaves (`kiro_id_token`, `kiro_access_token`, `kiro_refresh_token`, `kiro_token_expiry`)
    - _Requisitos: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 10.1, 10.2, 10.4_

  - [ ]* 4.2 Escrever teste de propriedade — Armazenamento de tokens (round-trip)
    - **Propriedade 1: Armazenamento de tokens após autenticação**
    - Gerar tokens JWT aleatórios com payloads variados usando fast-check
    - Verificar que após autenticação bem-sucedida (mockada), todos os tokens são armazenados no localStorage com as chaves corretas
    - Verificar que decodificar o id_token armazenado produz o mesmo payload original
    - **Valida: Requisitos 1.2, 5.6**

  - [ ]* 4.3 Escrever teste de propriedade — Autenticação direta sem redirecionamento
    - **Propriedade 4: Autenticação direta sem redirecionamento**
    - Gerar credenciais aleatórias usando fast-check
    - Verificar que o AuthProvider chama a API do Cognito diretamente e NÃO altera `window.location` para redirecionar a um domínio externo
    - **Valida: Requisito 5.1**

  - [ ]* 4.4 Escrever teste de propriedade — Renovação de tokens expirados
    - **Propriedade 5: Renovação de tokens expirados**
    - Gerar estados de token com diferentes combinações de expiração usando fast-check
    - Verificar que quando o id_token está expirado mas o refresh_token é válido, o AuthProvider tenta renovar a sessão antes de definir `isAuthenticated` como `false`
    - **Valida: Requisito 5.7**

  - [ ]* 4.5 Escrever teste de propriedade — Logout limpa estado sem redirecionamento
    - **Propriedade 6: Logout limpa estado sem redirecionamento externo**
    - Gerar estados autenticados com tokens variados usando fast-check
    - Verificar que o logout remove todas as chaves de token do localStorage, define `isAuthenticated` como `false` e `user` como `null`, e NÃO redireciona para endpoint externo
    - **Valida: Requisitos 10.1, 10.2, 10.4**

- [x] 5. Criar páginas de autenticação (Auth UI)
  - [x] 5.1 Criar LoginPage.tsx
    - Criar `frontend/src/pages/LoginPage.tsx` com formulário de email e senha usando componentes Cloudscape (`Form`, `FormField`, `Input`, `Button`, `Alert`, `Container`, `SpaceBetween`, `Box`, `Header`, `Link`)
    - Estilizar com tema escuro do Cloudscape
    - Chamar `login(email, password)` do AuthProvider ao enviar o formulário
    - Exibir mensagens de erro inline usando componente `Alert` com `type="error"`
    - Incluir link "Criar conta" navegando para `/signup`
    - Incluir link "Esqueci minha senha" navegando para `/forgot-password`
    - Unificar mensagens de `NotAuthorizedException` e `UserNotFoundException` como "Email ou senha incorretos." para evitar enumeração de contas
    - _Requisitos: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6_

  - [x] 5.2 Criar SignupPage.tsx
    - Criar `frontend/src/pages/SignupPage.tsx` com formulário de email, senha e confirmação de senha
    - Implementar etapa de código de confirmação: após cadastro bem-sucedido, exibir formulário para inserir código de verificação
    - Chamar `signup(email, password)` e `confirmSignup(email, code)` do AuthProvider
    - Exibir mensagem de erro para email duplicado (`UsernameExistsException`)
    - Exibir mensagem de erro para violação de política de senha (`InvalidPasswordException`)
    - Navegar para `/login` com mensagem de sucesso após confirmação
    - Incluir link "Voltar para login" navegando para `/login`
    - _Requisitos: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

  - [x] 5.3 Criar ForgotPasswordPage.tsx
    - Criar `frontend/src/pages/ForgotPasswordPage.tsx` com formulário solicitando email
    - Chamar `forgotPassword(email)` do AuthProvider ao enviar
    - Após envio bem-sucedido, navegar para `/reset-password` passando o email via state do React Router
    - _Requisitos: 3.1, 3.2_

  - [x] 5.4 Criar ResetPasswordPage.tsx
    - Criar `frontend/src/pages/ResetPasswordPage.tsx` com campos para código de verificação, nova senha e confirmação
    - Chamar `resetPassword(email, code, newPassword)` do AuthProvider
    - Exibir erro para código inválido ou expirado
    - Exibir erro para violação de política de senha
    - Navegar para `/login` com mensagem de sucesso após redefinição
    - _Requisitos: 3.3, 3.4, 3.5, 3.6_

  - [ ]* 5.5 Escrever teste de propriedade — Exibição de erros de autenticação
    - **Propriedade 2: Exibição de erros de autenticação**
    - Gerar erros Cognito aleatórios de uma lista de tipos conhecidos (`NotAuthorizedException`, `UserNotFoundException`, `UserNotConfirmedException`, etc.) usando fast-check
    - Verificar que a UI de login exibe uma mensagem de erro não-vazia e visível, sem lançar exceções não tratadas
    - **Valida: Requisito 1.3**

  - [ ]* 5.6 Escrever teste de propriedade — Exibição de erros de política de senha
    - **Propriedade 3: Exibição de erros de política de senha**
    - Gerar mensagens variadas de `InvalidPasswordException` (comprimento mínimo, maiúsculas, números, etc.) usando fast-check
    - Verificar que a Auth UI exibe uma mensagem de erro descritiva incluindo o requisito específico da política violada
    - **Valida: Requisitos 2.6, 3.6**

  - [ ]* 5.7 Escrever testes unitários para as páginas de autenticação
    - Testar renderização do LoginPage: verificar campos de email, senha e botão de envio
    - Testar renderização do SignupPage: verificar campos de email, senha, confirmação e botão
    - Testar renderização do ForgotPasswordPage: verificar campo de email e botão
    - Testar renderização do ResetPasswordPage: verificar campos de código, nova senha, confirmação e botão
    - Testar navegação entre páginas: links "Criar conta", "Esqueci minha senha", "Voltar para login"
    - Testar exibição do formulário de login após logout (10.3)
    - _Requisitos: 1.1, 1.5, 1.6, 2.1, 2.7, 3.1, 3.3, 10.3_

- [x] 6. Checkpoint — Validar autenticação e páginas
  - Garantir que todos os testes passam executando `npm run test` no diretório `frontend/`
  - Perguntar ao usuário se há dúvidas antes de prosseguir

- [x] 7. Atualizar roteamento da aplicação (App.tsx)
  - [x] 7.1 Refatorar App.tsx com novas rotas de autenticação
    - Importar as novas páginas: `LoginPage`, `SignupPage`, `ForgotPasswordPage`, `ResetPasswordPage`
    - Quando `!isAuthenticated`, renderizar rotas de auth (`/login`, `/signup`, `/forgot-password`, `/reset-password`) em vez do botão simples "Entrar"
    - Redirecionar usuários não autenticados para `/login` como rota padrão
    - Remover a rota `/callback` (não mais necessária com autenticação direta)
    - Manter todas as rotas protegidas existentes (`/`, `/account`, `/settings`, `/users`, `/user/:userId`)
    - _Requisitos: 1.1, 5.1 (fluxo sem redirect)_

- [x] 8. Criar Makefile para automação de deploy
  - [x] 8.1 Criar Makefile na raiz do projeto
    - Implementar target `deploy`: deploy completo (infra + frontend)
    - Implementar target `deploy-infra`: executa `sam build` + `sam deploy`
    - Implementar target `deploy-frontend`: gera `.env.production` a partir dos outputs do CloudFormation, executa `npm ci && npm run build`, faz `aws s3 sync dist/ s3://<WebsiteBucket>/ --delete`, executa `aws cloudfront create-invalidation --distribution-id <DistributionId> --paths "/*"`
    - Implementar target `dev`: executa `cd frontend && npm run dev`
    - Ler valores de `WebsiteBucket`, `CloudFrontDistributionId`, `ApiUrl`, `UserPoolId` e `UserPoolClientId` automaticamente dos outputs do CloudFormation via `aws cloudformation describe-stacks`
    - Gerar `frontend/.env.production` com `VITE_API_URL`, `VITE_COGNITO_USER_POOL_ID` e `VITE_COGNITO_CLIENT_ID` extraídos dos outputs
    - _Requisitos: (estratégia de deploy do design)_

- [ ] 9. Testes de infraestrutura (smoke tests)
  - [ ]* 9.1 Escrever testes de validação do template.yaml
    - Criar arquivo de teste que parseia o `template.yaml` e verifica:
      - `ExplicitAuthFlows` do CognitoUserPoolClient contém `ALLOW_USER_SRP_AUTH`, `ALLOW_USER_PASSWORD_AUTH` e `ALLOW_REFRESH_TOKEN_AUTH` (4.1, 4.2, 4.3)
      - `GenerateSecret` é `false` (4.4)
      - CloudFront Distribution está configurada com OAC, HTTPS redirect, `DefaultRootObject: index.html` (6.1, 6.2, 6.4)
      - Custom Error Responses para 403 e 404 retornam `/index.html` com status 200 (7.1, 7.2)
      - `CallbackURLs` inclui URL do CloudFront com `/callback` e `localhost:5173/callback` (8.1, 8.3)
      - `LogoutURLs` inclui URL do CloudFront raiz e `localhost:5173/` (8.2, 8.4)
      - Outputs `CloudFrontDomainName` e `CloudFrontDistributionId` existem (9.1, 9.2)
      - Standard Logging habilitado com prefixo `cloudfront-logs/` (11.1)
      - Monitoring Subscription habilitado (11.2)
      - Bucket policy de logs permite principal `logging.s3.amazonaws.com` (11.3)
    - _Requisitos: 4.1–4.4, 6.1–6.4, 7.1–7.2, 8.1–8.4, 9.1–9.2, 11.1–11.3_

- [x] 10. Checkpoint final — Garantir que todos os testes passam
  - Executar todos os testes do frontend (`npm run test` no diretório `frontend/`)
  - Executar validação do template (`sam validate`)
  - Perguntar ao usuário se há dúvidas

## Notas

- Tarefas marcadas com `*` são opcionais e podem ser puladas para um MVP mais rápido
- Cada tarefa referencia requisitos específicos para rastreabilidade
- Checkpoints garantem validação incremental
- Testes de propriedade validam propriedades universais de corretude definidas no design
- Testes unitários validam exemplos específicos e edge cases
- A linguagem de implementação é TypeScript (React/Cloudscape) para o frontend e YAML (SAM/CloudFormation) para a infraestrutura
