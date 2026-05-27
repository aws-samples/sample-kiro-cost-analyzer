# Plano de Implementação: Acesso Cross-Account ao S3

## Visão Geral

Implementação do padrão STS AssumeRole para permitir que as Lambdas do pipeline ETL acessem buckets S3 em contas AWS diferentes. A implementação segue uma abordagem incremental: primeiro a infraestrutura e módulos core, depois a integração nos handlers, e por fim o backend/frontend para configuração via UI.

## Tarefas

- [x] 1. Infraestrutura CloudFormation — parâmetro, SSM, condição e IAM policies
  - [x] 1.1 Adicionar parâmetro `SourceBucketRoleArn`, condição `HasSourceBucketRoleArn`, recurso SSM `SourceBucketRoleArnParameter` e variável de ambiente `SSM_SOURCE_BUCKET_ROLE_ARN` no `template.yaml`
    - Adicionar o parâmetro `SourceBucketRoleArn` (tipo String, default vazio) na seção `Parameters`
    - Criar a seção `Conditions` com `HasSourceBucketRoleArn: !Not [!Equals [!Ref SourceBucketRoleArn, ""]]`
    - Criar o recurso `SourceBucketRoleArnParameter` (AWS::SSM::Parameter) no caminho `/kiro-cost-analyzer/source-bucket-role-arn`
    - Adicionar `SSM_SOURCE_BUCKET_ROLE_ARN: /kiro-cost-analyzer/source-bucket-role-arn` nas variáveis de ambiente de `ListFilesFunction`, `ParseFunction` e `BackendFunction`
    - _Requisitos: 1.1, 1.2, 1.3, 1.4, 11.6_

  - [x] 1.2 Adicionar IAM policy condicional `sts:AssumeRole` nas funções `ListFilesFunction` e `ParseFunction`
    - Usar `!If [HasSourceBucketRoleArn, ...]` para adicionar policy `sts:AssumeRole` com `Resource: !Ref SourceBucketRoleArn` apenas quando o parâmetro for fornecido
    - Manter todas as IAM policies existentes de acesso direto ao S3 inalteradas
    - _Requisitos: 1.5, 7.4, 9.2_

  - [x] 1.3 Adicionar evento API Gateway `PUT /api/config/source-bucket-role-arn` na `BackendFunction`
    - Seguir o padrão dos eventos existentes (`ConfigPromptsPrefixPut`, `ConfigIdentityStoreIdPut`)
    - _Requisitos: 11.2_

- [x] 2. Checkpoint — Validar template
  - Executar `sam validate` para garantir que o `template.yaml` está válido. Perguntar ao usuário se houver dúvidas.

- [x] 3. Módulo STS Session Manager e configuração ETL
  - [x] 3.1 Criar o módulo `etl/sts_session.py` com a função `get_s3_client(role_arn, correlation_id)`
    - Implementar conforme o design: retornar `None` para role_arn vazio/None, chamar `sts:AssumeRole` com `DurationSeconds=3600` e `RoleSessionName` contendo o nome da Lambda (`AWS_LAMBDA_FUNCTION_NAME`)
    - Criar cliente boto3 S3 com as credenciais temporárias retornadas
    - Logar sucesso com `roleArn` e `sessionName` via `StructuredLogger`
    - Logar erros com `roleArn`, `sessionName`, `errorType`, `errorMessage` e sugestão de verificar trust policy para `AccessDenied`
    - Propagar exceções ao chamador sem silenciá-las
    - Adicionar import com fallback (`try/except ImportError`) seguindo o padrão do projeto
    - _Requisitos: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 8.1, 8.2, 8.3, 8.5, 9.1, 9.5, 9.6_

  - [ ]* 3.2 Escrever testes unitários para `etl/sts_session.py` em `tests/test_sts_session.py`
    - Testar `get_s3_client` com role_arn válido (mock STS retornando credenciais)
    - Testar `get_s3_client` com role_arn vazio e None (deve retornar None sem chamar STS)
    - Testar propagação de exceção quando `sts:AssumeRole` falha
    - Testar que `DurationSeconds=3600` é passado na chamada
    - Testar que `RoleSessionName` contém o nome da Lambda
    - _Requisitos: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 9.1, 9.5_

  - [ ]* 3.3 Escrever teste property-based para bypass single-account
    - **Propriedade 3: Bypass do STS para modo single-account**
    - Para qualquer valor de role_arn vazio (`""`) ou `None`, `get_s3_client` retorna `None` sem chamar STS
    - **Valida: Requisitos 3.6, 7.2, 7.3**

  - [ ]* 3.4 Escrever teste property-based para propagação de exceções
    - **Propriedade 6: Propagação de exceções do STS**
    - Para qualquer exceção lançada por `sts:AssumeRole`, `get_s3_client` propaga a exceção ao chamador
    - **Valida: Requisitos 3.5, 8.2**

  - [ ]* 3.5 Escrever teste property-based para rastreabilidade do session name
    - **Propriedade 7: Rastreabilidade do RoleSessionName**
    - Para qualquer nome de função Lambda em `AWS_LAMBDA_FUNCTION_NAME`, o `RoleSessionName` usado na chamada contém o nome da função
    - **Valida: Requisito 9.5**

  - [ ]* 3.6 Escrever teste property-based para criação da sessão STS
    - **Propriedade 2: Criação correta da sessão STS cross-account**
    - Para qualquer role_arn não-vazio e credenciais temporárias retornadas pelo STS, `get_s3_client` chama `sts:AssumeRole` com o ARN exato, `DurationSeconds=3600`, e retorna um cliente S3 configurado com as credenciais
    - **Valida: Requisitos 3.2, 3.3, 3.4, 9.1**

  - [x] 3.7 Adicionar campo `source_bucket_role_arn` ao `EtlConfig` em `etl/config.py` e ler do SSM
    - Adicionar o campo `source_bucket_role_arn: str` ao dataclass `EtlConfig`
    - Ler o valor do SSM via variável de ambiente `SSM_SOURCE_BUCKET_ROLE_ARN`, seguindo o padrão dos campos opcionais existentes (`prompts_prefix`, `identity_store_id`)
    - Retornar string vazia em caso de falha na leitura (fallback single-account)
    - Passar o novo campo no construtor de `EtlConfig`
    - _Requisitos: 2.1, 2.2, 2.3, 2.4, 7.5_

  - [ ]* 3.8 Atualizar testes existentes em `tests/test_etl_config.py` e adicionar testes para o novo campo
    - Testar leitura do `source_bucket_role_arn` com valor não-vazio do SSM
    - Testar leitura com valor vazio do SSM (retorna string vazia)
    - Testar fallback quando o parâmetro SSM não existe (retorna string vazia)
    - Garantir que os testes existentes continuam passando (campo adicionado ao dataclass)
    - _Requisitos: 2.1, 2.2, 2.3, 2.4_

  - [ ]* 3.9 Escrever teste property-based para leitura do Role ARN do SSM
    - **Propriedade 1: Leitura do Role ARN do SSM preserva o valor**
    - Para qualquer string retornada pelo SSM (incluindo vazia), `get_config()` retorna um `EtlConfig` cujo `source_bucket_role_arn` é idêntico ao valor lido
    - **Valida: Requisitos 2.2, 2.3**

- [x] 4. Checkpoint — Executar testes dos módulos core
  - Executar `pytest tests/test_sts_session.py tests/test_etl_config.py -v` para garantir que os módulos core estão corretos. Perguntar ao usuário se houver dúvidas.

- [x] 5. Injeção de cliente S3 nos readers e integração nos handlers
  - [x] 5.1 Adicionar parâmetro opcional `s3_client` às funções `list_csv_files` e `read_csv_content` em `etl/s3_reader.py`
    - Alterar assinatura para `list_csv_files(bucket, prefix, s3_client=None)` e `read_csv_content(bucket, key, s3_client=None)`
    - Usar `s3 = s3_client or boto3.client("s3")` no início de cada função
    - _Requisitos: 4.5, 5.5_

  - [x] 5.2 Adicionar parâmetro opcional `s3_client` às funções `list_prompt_files` e `read_prompt_file` em `etl/prompt_s3_reader.py`
    - Alterar assinatura para `list_prompt_files(bucket, prompts_prefix, s3_client=None)` e `read_prompt_file(bucket, key, s3_client=None)`
    - Usar `s3 = s3_client or boto3.client("s3")` no início de cada função
    - _Requisitos: 4.5, 5.5_

  - [ ]* 5.3 Escrever teste property-based para injeção de cliente S3 nas funções de listagem
    - **Propriedade 4: Injeção de cliente S3 nas funções de listagem**
    - Para qualquer cliente S3 fornecido como `s3_client`, `list_csv_files` e `list_prompt_files` usam exclusivamente esse cliente para `list_objects_v2`, sem criar novo `boto3.client("s3")`
    - **Valida: Requisitos 4.2, 4.3, 4.5**

  - [ ]* 5.4 Escrever teste property-based para injeção de cliente S3 nas funções de leitura
    - **Propriedade 5: Injeção de cliente S3 nas funções de leitura**
    - Para qualquer cliente S3 fornecido como `s3_client`, `read_csv_content` e `read_prompt_file` usam exclusivamente esse cliente para `get_object`, sem criar novo `boto3.client("s3")`
    - **Valida: Requisitos 5.2, 5.3, 5.5**

  - [x] 5.5 Integrar `get_s3_client` no `etl/list_handler.py`
    - Adicionar import de `sts_session.get_s3_client` com fallback `try/except ImportError`
    - Após `get_config()`, chamar `get_s3_client(cfg.source_bucket_role_arn, correlation_id=correlation_id)`
    - Passar `s3_client=cross_account_client` para `list_csv_files` e `list_prompt_files`
    - _Requisitos: 4.1, 4.2, 4.3, 4.4_

  - [x] 5.6 Integrar `get_s3_client` no `etl/parse_handler.py`
    - Adicionar import de `sts_session.get_s3_client` com fallback `try/except ImportError`
    - Após `get_config()`, chamar `get_s3_client(cfg.source_bucket_role_arn, correlation_id=correlation_id)`
    - Passar `s3_client=cross_account_client` para `_process_csv_file` e `_process_prompt_file`, que repassam para `read_csv_content` e `read_prompt_file`
    - Logar erro com `roleArn`, `bucket`, `key` e sugestão de verificar permissões da Role_Origem quando S3 retornar `AccessDenied`
    - _Requisitos: 5.1, 5.2, 5.3, 5.4, 8.4_

  - [ ]* 5.7 Atualizar testes existentes em `tests/test_list_handler.py` e `tests/test_parse_handler.py`
    - Adicionar testes para modo cross-account (mock `get_s3_client` retornando cliente mockado)
    - Adicionar testes para modo single-account (mock `get_s3_client` retornando None)
    - Garantir que testes existentes continuam passando
    - _Requisitos: 4.1, 4.4, 5.1, 5.4, 7.2, 7.3_

- [x] 6. Checkpoint — Executar testes do pipeline ETL
  - Executar `pytest tests/test_s3_reader.py tests/test_prompt_s3_reader.py tests/test_list_handler.py tests/test_parse_handler.py -v` para garantir que a integração está correta. Perguntar ao usuário se houver dúvidas.

- [x] 7. Backend — endpoint de configuração e roteamento
  - [x] 7.1 Adicionar handler `handle_put_config_source_bucket_role_arn` em `backend/handlers/config_handler.py` e atualizar `handle_get_config`
    - Implementar `handle_put_config_source_bucket_role_arn(body, ssm_client=None)` com validação de formato ARN via regex `^arn:aws:iam::\d{12}:role/.+$`
    - Permitir valor vazio (desabilita cross-account) e salvar no SSM
    - Retornar erro com mensagem descritiva para formato inválido, sem salvar no SSM
    - Atualizar `handle_get_config` para ler e retornar `sourceBucketRoleArn` do SSM
    - _Requisitos: 11.1, 11.2, 11.3, 11.4, 11.5, 11.8_

  - [x] 7.2 Adicionar rota `PUT /api/config/source-bucket-role-arn` no roteador `backend/handler.py`
    - Seguir o padrão das rotas existentes de config (`/api/config/prompts-prefix`, `/api/config/identity-store-id`)
    - Proteger com verificação de admin (`_is_admin(claims)`)
    - Chamar `config_handler.handle_put_config_source_bucket_role_arn(body)`
    - _Requisitos: 11.2_

  - [ ]* 7.3 Escrever testes unitários para o novo handler e atualizar testes do GET config em `tests/test_config_handler.py`
    - Testar `handle_put_config_source_bucket_role_arn` com ARN válido, ARN inválido e valor vazio
    - Testar que `handle_get_config` retorna `sourceBucketRoleArn`
    - _Requisitos: 11.1, 11.3, 11.4, 11.5_

  - [ ]* 7.4 Escrever teste property-based para validação de formato ARN
    - **Propriedade 8: Validação de formato ARN no endpoint de configuração**
    - Para qualquer string fornecida: vazio → salva e retorna `valid`; match `arn:aws:iam::\d{12}:role/.+` → salva e retorna `valid`; não match → retorna `error` sem salvar
    - **Valida: Requisitos 11.3, 11.4, 11.5**

  - [ ]* 7.5 Atualizar testes do roteador em `tests/test_backend_handler.py`
    - Testar rota `PUT /api/config/source-bucket-role-arn` com admin e não-admin
    - _Requisitos: 11.2_

- [x] 8. Checkpoint — Executar testes do backend
  - Executar `pytest tests/test_config_handler.py tests/test_backend_handler.py -v` para garantir que o backend está correto. Perguntar ao usuário se houver dúvidas.

- [x] 9. Frontend — campo de configuração na página de Settings
  - [x] 9.1 Adicionar campo `sourceBucketRoleArn` na interface `AppConfig` em `frontend/src/types/index.ts` e na página `frontend/src/pages/SettingsPage.tsx`
    - Adicionar `sourceBucketRoleArn?: string` à interface `AppConfig`
    - Adicionar estado `sourceBucketRoleArn` com `useState`
    - Carregar o valor no `fetchConfig` a partir da resposta do GET `/api/config`
    - Adicionar campo `Input` do Cloudscape com label "Source Bucket Role ARN" e descrição "ARN da IAM Role cross-account para acesso ao bucket S3 de origem (vazio = single-account)"
    - Adicionar botão "Salvar" que chama `PUT /api/config/source-bucket-role-arn` com body `{ sourceBucketRoleArn }`
    - Seguir o padrão visual e de feedback (success/error) dos campos existentes (prompts prefix, identity store ID)
    - Permitir limpar o campo para desabilitar cross-account
    - _Requisitos: 11.7, 11.8_

- [x] 10. Template helper e Makefile
  - [x] 10.1 Criar o template `source-account-role.yaml` na raiz do projeto
    - Implementar conforme o design: parâmetros `KiroAccountId`, `SourceBucketName`, `KMSKeyArn` (opcional)
    - Criar IAM Role com trust policy restrita à conta `KiroAccountId` usando condição `aws:PrincipalAccount`
    - Anexar policy S3 com `s3:ListBucket` e `s3:GetObject`
    - Anexar policy KMS condicional (`HasKMSKey`) com `kms:Decrypt` e `kms:DescribeKey`
    - Exportar `CrossAccountRoleArn` como Output
    - _Requisitos: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 9.3, 9.4_

  - [x] 10.2 Adicionar target `deploy-source-role` no `Makefile`
    - Implementar conforme o design: variáveis `SOURCE_ACCOUNT_PROFILE`, `KIRO_ACCOUNT_ID`, `SOURCE_BUCKET_NAME`, `KMS_KEY_ARN` (opcional), `SOURCE_ROLE_STACK_NAME` (default `kiro-cross-account-role`)
    - Validar parâmetros obrigatórios com mensagem de erro
    - Executar `aws cloudformation deploy` com `--capabilities CAPABILITY_NAMED_IAM`
    - Exibir o ARN da role criada após deploy bem-sucedido
    - _Requisitos: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9_

- [x] 11. Checkpoint final — Executar todos os testes
  - Executar `pytest tests/ -v` para garantir que todos os testes passam e não há regressões. Perguntar ao usuário se houver dúvidas.

## Notas

- Tarefas marcadas com `*` são opcionais e podem ser puladas para um MVP mais rápido
- Cada tarefa referencia requisitos específicos para rastreabilidade
- Checkpoints garantem validação incremental entre grupos de tarefas
- Testes property-based validam as 8 propriedades de corretude definidas no design
- Testes unitários validam cenários específicos e edge cases
- A implementação é retrocompatível: deployments single-account continuam funcionando sem alteração
