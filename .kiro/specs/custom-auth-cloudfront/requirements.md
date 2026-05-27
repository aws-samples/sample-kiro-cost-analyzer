# Documento de Requisitos

## Introdução

Esta feature substitui o redirecionamento para a Hosted UI do Cognito por uma UI customizada de login, cadastro e recuperação de senha construída diretamente no frontend React/Cloudscape. Também provisiona uma distribuição CloudFront com o S3 WebsiteBucket como origem para servir a SPA publicamente via HTTPS, com roteamento SPA e URLs de callback do Cognito atualizadas.

## Glossário

- **Auth_UI**: Conjunto de páginas React customizadas (login, cadastro, esqueci-senha, redefinir-senha) renderizadas dentro do frontend usando componentes Cloudscape no tema escuro.
- **Cognito_Client**: O User Pool Client do Cognito (`CognitoUserPoolClient`) configurado para a SPA, suportando autenticação direta via API do Cognito (USER_SRP_AUTH, USER_PASSWORD_AUTH).
- **Auth_Provider**: O context provider React (`AuthProvider.tsx`) que gerencia o estado de autenticação, armazenamento de tokens e expõe funções de login/logout/cadastro para a aplicação.
- **CloudFront_Distribution**: A distribuição CloudFront que serve a SPA do frontend a partir do S3 WebsiteBucket com HTTPS e roteamento SPA.
- **WebsiteBucket**: O bucket S3 existente (`${StackName}-website-${AWS::AccountId}`) destinado a hospedar os artefatos de build do frontend.
- **OAC**: Origin Access Control, mecanismo do CloudFront que concede à distribuição acesso de leitura ao bucket S3 privado sem torná-lo público.
- **SPA_Routing**: Configuração do CloudFront que redireciona respostas HTTP 403/404 para `/index.html` para que o roteamento client-side funcione corretamente.
- **Callback_URL**: URL registrada no Cognito_Client como destino de redirecionamento permitido após autenticação.

## Requisitos

### Requisito 1: Página de Login Customizada

**História de Usuário:** Como usuário, quero fazer login usando um formulário dentro da aplicação, para não ser redirecionado para a Hosted UI externa do Cognito.

#### Critérios de Aceitação

1. QUANDO um usuário navega para a aplicação sem estar autenticado, A Auth_UI DEVE exibir um formulário de login com campos de email e senha e um botão de envio.
2. QUANDO um usuário envia credenciais válidas no formulário de login, O Auth_Provider DEVE autenticar o usuário no Cognito User Pool usando a API do Cognito e armazenar os tokens resultantes no localStorage.
3. QUANDO um usuário envia credenciais inválidas no formulário de login, A Auth_UI DEVE exibir uma mensagem de erro inline descrevendo a falha de autenticação.
4. A Auth_UI DEVE renderizar o formulário de login usando componentes do Cloudscape Design System estilizados com o tema escuro.
5. QUANDO um usuário clica no link "Criar conta" no formulário de login, A Auth_UI DEVE navegar para a página de cadastro.
6. QUANDO um usuário clica no link "Esqueci minha senha" no formulário de login, A Auth_UI DEVE navegar para a página de recuperação de senha.

### Requisito 2: Página de Cadastro Customizada

**História de Usuário:** Como novo usuário, quero criar uma conta de dentro da aplicação, para me registrar sem sair do app.

#### Critérios de Aceitação

1. QUANDO um usuário navega para a página de cadastro, A Auth_UI DEVE exibir um formulário de registro com campos de email, senha e confirmação de senha.
2. QUANDO um usuário envia o formulário de cadastro com dados válidos, O Auth_Provider DEVE criar um novo usuário no Cognito User Pool usando a API do Cognito.
3. QUANDO o Cognito User Pool exige verificação de email após o cadastro, A Auth_UI DEVE exibir um formulário de entrada do código de confirmação.
4. QUANDO um usuário envia um código de confirmação válido, O Auth_Provider DEVE confirmar a conta do usuário e navegar para a página de login com uma mensagem de sucesso.
5. SE a requisição de cadastro falhar por email duplicado, ENTÃO A Auth_UI DEVE exibir uma mensagem de erro indicando que a conta já existe.
6. SE a requisição de cadastro falhar por violação da política de senha, ENTÃO A Auth_UI DEVE exibir uma mensagem de erro descrevendo o requisito específico da política.
7. QUANDO um usuário clica no link "Voltar para login" na página de cadastro, A Auth_UI DEVE navegar para a página de login.

### Requisito 3: Fluxo de Esqueci Senha e Redefinição de Senha

**História de Usuário:** Como usuário que esqueceu a senha, quero redefini-la de dentro da aplicação, para recuperar o acesso sem páginas externas.

#### Critérios de Aceitação

1. QUANDO um usuário navega para a página de esqueci-senha, A Auth_UI DEVE exibir um formulário solicitando o email do usuário.
2. QUANDO um usuário envia um email válido no formulário de esqueci-senha, O Auth_Provider DEVE iniciar o fluxo de redefinição de senha via API do Cognito, que envia um código de verificação para o email.
3. QUANDO o código de verificação foi enviado, A Auth_UI DEVE exibir um formulário de redefinição de senha com campos para o código de verificação, nova senha e confirmação da nova senha.
4. QUANDO um usuário envia um código de verificação válido e nova senha, O Auth_Provider DEVE completar a redefinição de senha via API do Cognito e navegar para a página de login com uma mensagem de sucesso.
5. SE o código de verificação for inválido ou expirado, ENTÃO A Auth_UI DEVE exibir uma mensagem de erro indicando que o código é inválido ou expirou.
6. SE a nova senha não atender à política de senha do Cognito, ENTÃO A Auth_UI DEVE exibir uma mensagem de erro descrevendo o requisito específico da política.

### Requisito 4: Configuração do Cognito Client para Autenticação Direta via API

**História de Usuário:** Como desenvolvedor, quero que o Cognito User Pool Client suporte autenticação direta via API, para que a Auth_UI customizada possa autenticar usuários sem a Hosted UI.

#### Critérios de Aceitação

1. O Cognito_Client DEVE incluir `ALLOW_USER_SRP_AUTH` nos ExplicitAuthFlows para suportar autenticação direta segura a partir da Auth_UI.
2. O Cognito_Client DEVE incluir `ALLOW_USER_PASSWORD_AUTH` nos ExplicitAuthFlows para suportar autenticação por usuário/senha a partir da Auth_UI.
3. O Cognito_Client DEVE manter `ALLOW_REFRESH_TOKEN_AUTH` nos ExplicitAuthFlows para suportar renovação de tokens.
4. O Cognito_Client DEVE manter `GenerateSecret: false` já que o client é usado por uma SPA pública.

### Requisito 5: Refatoração do Auth Provider

**História de Usuário:** Como desenvolvedor, quero que o Auth_Provider use chamadas diretas à API do Cognito em vez do fluxo de redirect OAuth2/PKCE, para que a autenticação aconteça inteiramente dentro da aplicação.

#### Critérios de Aceitação

1. O Auth_Provider DEVE autenticar usuários chamando a API do Cognito diretamente (usando `InitiateAuth` ou método equivalente do SDK) em vez de redirecionar para a Hosted UI do Cognito.
2. O Auth_Provider DEVE suportar cadastro chamando a API `SignUp` do Cognito.
3. O Auth_Provider DEVE suportar confirmação de email chamando a API `ConfirmSignUp` do Cognito.
4. O Auth_Provider DEVE suportar esqueci-senha chamando a API `ForgotPassword` do Cognito.
5. O Auth_Provider DEVE suportar redefinição de senha chamando a API `ConfirmForgotPassword` do Cognito.
6. O Auth_Provider DEVE armazenar id_token, access_token e refresh_token no localStorage após autenticação bem-sucedida.
7. QUANDO os tokens armazenados estiverem expirados, O Auth_Provider DEVE tentar renová-los usando o refresh_token antes de exigir re-autenticação.
8. O Auth_Provider DEVE expor as funções `login`, `signup`, `confirmSignup`, `forgotPassword`, `resetPassword` e `logout` via React context.

### Requisito 6: Distribuição CloudFront com Origem S3

**História de Usuário:** Como desenvolvedor, quero a SPA do frontend servida via CloudFront com o S3 WebsiteBucket como origem, para que os usuários acessem a aplicação via HTTPS com baixa latência.

#### Critérios de Aceitação

1. A CloudFront_Distribution DEVE usar o WebsiteBucket como origem via configuração OAC.
2. A CloudFront_Distribution DEVE usar a configuração `ViewerProtocolPolicy: redirect-to-https` para forçar HTTPS em todas as requisições.
3. O WebsiteBucket DEVE ter uma bucket policy que concede à CloudFront_Distribution acesso de leitura via principal OAC.
4. A CloudFront_Distribution DEVE definir o objeto raiz padrão como `index.html`.

### Requisito 7: Roteamento SPA via Custom Error Responses do CloudFront

**História de Usuário:** Como usuário, quero navegar diretamente para qualquer rota da aplicação via URL, para que deep links e refresh de página funcionem corretamente.

#### Critérios de Aceitação

1. QUANDO o CloudFront receber uma resposta 403 do S3 para um caminho solicitado, A CloudFront_Distribution DEVE retornar `/index.html` com status HTTP 200.
2. QUANDO o CloudFront receber uma resposta 404 do S3 para um caminho solicitado, A CloudFront_Distribution DEVE retornar `/index.html` com status HTTP 200.

### Requisito 8: Atualização das URLs de Callback do Cognito para o Domínio CloudFront

**História de Usuário:** Como desenvolvedor, quero que as URLs de callback e logout do Cognito incluam o domínio CloudFront, para que a autenticação funcione quando o app é acessado via CloudFront.

#### Critérios de Aceitação

1. O Cognito_Client DEVE incluir a URL do domínio da CloudFront_Distribution com o path `/callback` na lista de CallbackURLs.
2. O Cognito_Client DEVE incluir a URL do domínio da CloudFront_Distribution (path raiz) na lista de LogoutURLs.
3. O Cognito_Client DEVE manter a URL existente `http://localhost:5173/callback` para desenvolvimento local.
4. O Cognito_Client DEVE manter a URL existente `http://localhost:5173/` para logout em desenvolvimento local.

### Requisito 9: Output do Domínio CloudFront

**História de Usuário:** Como desenvolvedor, quero o nome de domínio da distribuição CloudFront disponível como output do CloudFormation, para configurar o ambiente do frontend e DNS.

#### Critérios de Aceitação

1. O template.yaml DEVE incluir um output do CloudFormation chamado `CloudFrontDomainName` contendo o nome de domínio da CloudFront_Distribution.
2. O template.yaml DEVE incluir um output do CloudFormation chamado `CloudFrontDistributionId` contendo o ID da CloudFront_Distribution.

### Requisito 10: Logout Sem Hosted UI

**História de Usuário:** Como usuário, quero fazer logout de dentro da aplicação sem ser redirecionado para uma página externa de logout do Cognito.

#### Critérios de Aceitação

1. QUANDO um usuário aciona o logout, O Auth_Provider DEVE limpar todos os tokens armazenados do localStorage.
2. QUANDO um usuário aciona o logout, O Auth_Provider DEVE resetar o estado de autenticação para não-autenticado.
3. QUANDO um usuário aciona o logout, A Auth_UI DEVE exibir o formulário de login.
4. O Auth_Provider DEVE realizar o logout localmente sem redirecionar para o endpoint de logout da Hosted UI do Cognito.

### Requisito 11: Logs Avançados do CloudFront

**História de Usuário:** Como desenvolvedor/operador, quero logs avançados habilitados na distribuição CloudFront, para ter visibilidade detalhada sobre o tráfego, latência e erros da aplicação.

#### Critérios de Aceitação

1. A CloudFront_Distribution DEVE ter os Standard Logging (access logs) habilitados, gravando os logs no DataBucket com o prefixo `cloudfront-logs/`.
2. A CloudFront_Distribution DEVE ter o Real-Time Monitoring habilitado via CloudFront Monitoring Metrics (métricas adicionais do CloudWatch) para visibilidade de cache hit ratio, latência por status code e erros por origem.
3. O bucket de destino dos logs DEVE ter uma bucket policy que permita ao CloudFront gravar os logs (principal `logging.s3.amazonaws.com`).
