# Documento de Requisitos — Acesso Cross-Account ao S3

## Introdução

O Kiro Cost Analyzer atualmente opera em modo single-account: o bucket S3 de origem (CSVs de atividade e logs de prompt) reside na mesma conta AWS da solução. Em ambientes enterprise, o bucket de origem frequentemente pertence a uma conta AWS diferente (ex: conta de logging centralizado). Esta feature implementa o padrão **STS AssumeRole** para permitir que as Lambdas do pipeline ETL assumam uma IAM Role na conta de origem, obtendo credenciais temporárias para acessar o bucket S3 cross-account. A solução deve ser retrocompatível — deployments single-account continuam funcionando sem alteração.

## Glossário

- **Pipeline_ETL**: Pipeline Step Functions (Standard + Distributed Map Express) composto pelas Lambdas `ListFilesFunction` e `ParseFunction` que leem dados do bucket S3 de origem
- **Conta_Kiro**: Conta AWS onde o Kiro Cost Analyzer está deployado (Lambdas, Step Functions, DynamoDB, API Gateway)
- **Conta_Origem**: Conta AWS onde reside o bucket S3 de origem com os CSVs de atividade e logs de prompt
- **Role_Origem**: IAM Role criada na Conta_Origem que concede permissões de leitura ao bucket S3 e decriptação KMS, com trust policy permitindo que a Conta_Kiro a assuma
- **Sessão_Cross_Account**: Sessão boto3 temporária obtida via `sts:AssumeRole` com credenciais de curta duração (padrão 900s) para acessar recursos na Conta_Origem
- **SourceBucketRoleArn**: Parâmetro opcional do CloudFormation que contém o ARN da Role_Origem; quando vazio, o sistema opera em modo single-account
- **Template_Helper**: Template CloudFormation auxiliar (`source-account-role.yaml`) que administradores da Conta_Origem deployam para criar a Role_Origem com as permissões e trust policy corretas
- **Gerenciador_STS**: Módulo Python compartilhado (`etl/sts_session.py`) responsável por criar e gerenciar Sessões_Cross_Account via STS AssumeRole
- **SSM_Parameter_Store**: Serviço AWS usado para armazenar configurações dinâmicas do ETL, incluindo o SourceBucketRoleArn
- **Target_Deploy_Role**: Target `deploy-source-role` do Makefile que automatiza o deploy do Template_Helper na Conta_Origem via `aws cloudformation deploy`

## Requisitos

### Requisito 1: Parâmetro Opcional de Role ARN no CloudFormation

**User Story:** Como administrador do Kiro Cost Analyzer, eu quero fornecer opcionalmente o ARN de uma IAM Role cross-account durante o deploy, para que o pipeline ETL possa acessar buckets S3 em outras contas AWS.

#### Critérios de Aceitação

1. THE template.yaml SHALL definir um parâmetro `SourceBucketRoleArn` do tipo `String` com valor padrão vazio (`""`)
2. WHEN o parâmetro `SourceBucketRoleArn` for fornecido com um valor não-vazio, THE template.yaml SHALL criar um recurso SSM Parameter Store no caminho `/kiro-cost-analyzer/source-bucket-role-arn` com o valor do ARN
3. WHEN o parâmetro `SourceBucketRoleArn` for vazio, THE template.yaml SHALL criar o recurso SSM Parameter Store no caminho `/kiro-cost-analyzer/source-bucket-role-arn` com valor vazio
4. THE template.yaml SHALL passar a variável de ambiente `SSM_SOURCE_BUCKET_ROLE_ARN` com o caminho `/kiro-cost-analyzer/source-bucket-role-arn` para as funções `ListFilesFunction` e `ParseFunction`
5. WHEN o parâmetro `SourceBucketRoleArn` for fornecido com um valor não-vazio, THE template.yaml SHALL conceder permissão `sts:AssumeRole` ao ARN especificado nas IAM policies das funções `ListFilesFunction` e `ParseFunction`

### Requisito 2: Leitura da Configuração de Role ARN

**User Story:** Como desenvolvedor do pipeline ETL, eu quero que o módulo de configuração leia o Role ARN do SSM Parameter Store, para que os handlers possam determinar se devem usar acesso cross-account.

#### Critérios de Aceitação

1. THE EtlConfig SHALL incluir um campo `source_bucket_role_arn` do tipo `str`
2. WHEN o parâmetro SSM `/kiro-cost-analyzer/source-bucket-role-arn` existir e contiver um valor não-vazio, THE função `get_config()` SHALL retornar o valor no campo `source_bucket_role_arn`
3. WHEN o parâmetro SSM `/kiro-cost-analyzer/source-bucket-role-arn` existir e contiver um valor vazio, THE função `get_config()` SHALL retornar string vazia no campo `source_bucket_role_arn`
4. IF a leitura do parâmetro SSM `/kiro-cost-analyzer/source-bucket-role-arn` falhar, THEN THE função `get_config()` SHALL retornar string vazia no campo `source_bucket_role_arn` e continuar a execução

### Requisito 3: Gerenciamento de Sessão STS Cross-Account

**User Story:** Como desenvolvedor do pipeline ETL, eu quero um módulo centralizado para gerenciar sessões STS cross-account, para que a lógica de AssumeRole seja reutilizável e testável.

#### Critérios de Aceitação

1. THE Gerenciador_STS SHALL expor uma função `get_s3_client(role_arn: str)` que retorna um cliente boto3 S3 com credenciais temporárias obtidas via `sts:AssumeRole`
2. WHEN a função `get_s3_client` receber um `role_arn` não-vazio, THE Gerenciador_STS SHALL chamar `sts:AssumeRole` com o ARN fornecido e um `RoleSessionName` que identifique a Lambda de origem
3. WHEN a função `get_s3_client` receber um `role_arn` não-vazio, THE Gerenciador_STS SHALL configurar `DurationSeconds` de 3600 segundos (1 hora) para as credenciais temporárias
4. WHEN a chamada `sts:AssumeRole` for bem-sucedida, THE Gerenciador_STS SHALL criar e retornar um cliente boto3 S3 usando `AccessKeyId`, `SecretAccessKey` e `SessionToken` das credenciais temporárias
5. IF a chamada `sts:AssumeRole` falhar, THEN THE Gerenciador_STS SHALL logar o erro com detalhes (ARN da role, tipo de exceção, mensagem) e propagar a exceção
6. WHEN a função `get_s3_client` receber um `role_arn` vazio ou `None`, THE Gerenciador_STS SHALL retornar `None` para indicar que o modo single-account deve ser usado

### Requisito 4: Acesso Cross-Account na Listagem de Arquivos

**User Story:** Como operador do pipeline ETL, eu quero que a Lambda de listagem de arquivos use credenciais cross-account quando configurado, para que o pipeline possa listar arquivos em buckets de outras contas.

#### Critérios de Aceitação

1. WHEN o campo `source_bucket_role_arn` da configuração contiver um valor não-vazio, THE `list_handler` SHALL obter um cliente S3 cross-account via Gerenciador_STS antes de listar arquivos
2. WHEN um cliente S3 cross-account estiver disponível, THE função `list_csv_files` SHALL usar o cliente fornecido em vez de criar um novo `boto3.client("s3")`
3. WHEN um cliente S3 cross-account estiver disponível, THE função `list_prompt_files` SHALL usar o cliente fornecido em vez de criar um novo `boto3.client("s3")`
4. WHEN o campo `source_bucket_role_arn` da configuração estiver vazio, THE `list_handler` SHALL manter o comportamento atual usando `boto3.client("s3")` padrão
5. THE funções `list_csv_files` e `list_prompt_files` SHALL aceitar um parâmetro opcional `s3_client` que, quando fornecido, substitui a criação interna do cliente boto3

### Requisito 5: Acesso Cross-Account no Parsing de Arquivos

**User Story:** Como operador do pipeline ETL, eu quero que a Lambda de parsing use credenciais cross-account quando configurado, para que o pipeline possa ler e processar arquivos de buckets em outras contas.

#### Critérios de Aceitação

1. WHEN o campo `source_bucket_role_arn` da configuração contiver um valor não-vazio, THE `parse_handler` SHALL obter um cliente S3 cross-account via Gerenciador_STS antes de ler arquivos
2. WHEN um cliente S3 cross-account estiver disponível, THE função `read_csv_content` SHALL usar o cliente fornecido em vez de criar um novo `boto3.client("s3")`
3. WHEN um cliente S3 cross-account estiver disponível, THE função `read_prompt_file` SHALL usar o cliente fornecido em vez de criar um novo `boto3.client("s3")`
4. WHEN o campo `source_bucket_role_arn` da configuração estiver vazio, THE `parse_handler` SHALL manter o comportamento atual usando `boto3.client("s3")` padrão
5. THE funções `read_csv_content` e `read_prompt_file` SHALL aceitar um parâmetro opcional `s3_client` que, quando fornecido, substitui a criação interna do cliente boto3

### Requisito 6: Template Helper para Conta de Origem

**User Story:** Como administrador da conta de origem, eu quero um template CloudFormation pronto para uso que crie a IAM Role com as permissões corretas, para que eu possa habilitar o acesso cross-account com esforço mínimo de configuração.

#### Critérios de Aceitação

1. THE Template_Helper SHALL ser um arquivo CloudFormation válido nomeado `source-account-role.yaml` na raiz do projeto
2. THE Template_Helper SHALL requerer dois parâmetros obrigatórios: `KiroAccountId` (ID da conta AWS do Kiro) e `SourceBucketName` (nome do bucket S3 de origem)
3. THE Template_Helper SHALL aceitar um parâmetro opcional `KMSKeyArn` com valor padrão vazio para cenários onde o bucket usa criptografia KMS CMK
4. THE Template_Helper SHALL criar uma IAM Role com trust policy que permita apenas a conta especificada em `KiroAccountId` assumir a role via `sts:AssumeRole`
5. THE Template_Helper SHALL anexar à IAM Role uma policy com permissões `s3:ListBucket` no bucket e `s3:GetObject` em todos os objetos do bucket especificado em `SourceBucketName`
6. WHEN o parâmetro `KMSKeyArn` for fornecido com um valor não-vazio, THE Template_Helper SHALL anexar à IAM Role permissões `kms:Decrypt` e `kms:DescribeKey` para a chave KMS especificada
7. THE Template_Helper SHALL exportar o ARN da IAM Role criada como Output nomeado `CrossAccountRoleArn`
8. THE Template_Helper SHALL usar a condição `HasKMSKey` para aplicar a policy KMS apenas quando o parâmetro `KMSKeyArn` for fornecido

### Requisito 7: Retrocompatibilidade com Modo Single-Account

**User Story:** Como usuário existente do Kiro Cost Analyzer em modo single-account, eu quero que o sistema continue funcionando sem alterações na minha configuração, para que a adição da feature cross-account não quebre meu deployment atual.

#### Critérios de Aceitação

1. WHEN o parâmetro `SourceBucketRoleArn` estiver vazio no deploy, THE Pipeline_ETL SHALL executar com o mesmo comportamento de acesso S3 direto existente antes desta feature
2. WHEN o parâmetro `SourceBucketRoleArn` estiver vazio, THE `list_handler` SHALL criar clientes S3 usando `boto3.client("s3")` sem nenhuma chamada STS
3. WHEN o parâmetro `SourceBucketRoleArn` estiver vazio, THE `parse_handler` SHALL criar clientes S3 usando `boto3.client("s3")` sem nenhuma chamada STS
4. THE template.yaml SHALL manter todas as IAM policies existentes de acesso direto ao S3 (`s3:ListBucket`, `s3:GetObject`, `kms:Decrypt`) inalteradas, independentemente do valor de `SourceBucketRoleArn`
5. THE EtlConfig SHALL manter todos os campos existentes (`bucket_name`, `source_prefix`, `prompts_prefix`, `identity_store_id`) com o mesmo comportamento de leitura

### Requisito 8: Tratamento de Erros e Observabilidade

**User Story:** Como operador do pipeline ETL, eu quero que erros de acesso cross-account sejam logados com detalhes suficientes para diagnóstico, para que eu possa identificar e resolver problemas de configuração rapidamente.

#### Critérios de Aceitação

1. IF a chamada `sts:AssumeRole` falhar com `AccessDeniedException`, THEN THE Gerenciador_STS SHALL logar uma mensagem de erro incluindo o ARN da role, o tipo de exceção e uma sugestão de verificar a trust policy da Role_Origem
2. IF a chamada `sts:AssumeRole` falhar com qualquer exceção, THEN THE Gerenciador_STS SHALL propagar a exceção para que o Step Functions execute a política de retry configurada
3. WHEN o Gerenciador_STS criar uma Sessão_Cross_Account com sucesso, THE Gerenciador_STS SHALL logar uma mensagem informativa incluindo o ARN da role assumida (sem expor credenciais)
4. IF um cliente S3 cross-account retornar `AccessDenied` ao acessar o bucket, THEN THE handler correspondente SHALL logar o erro com o ARN da role, o bucket, a chave S3 e uma sugestão de verificar as permissões da Role_Origem
5. THE Gerenciador_STS SHALL usar o `StructuredLogger` com campos consistentes (`roleArn`, `sessionName`, `errorType`, `errorMessage`) para todas as operações de logging

### Requisito 9: Segurança do Acesso Cross-Account

**User Story:** Como arquiteto de segurança, eu quero que o acesso cross-account siga o princípio de menor privilégio e use credenciais temporárias, para que o risco de acesso não autorizado seja minimizado.

#### Critérios de Aceitação

1. THE Gerenciador_STS SHALL usar credenciais temporárias com duração de 3600 segundos (1 hora) para cada chamada AssumeRole
2. THE template.yaml SHALL conceder permissão `sts:AssumeRole` apenas para o ARN específico fornecido em `SourceBucketRoleArn`, sem usar wildcards
3. THE Template_Helper SHALL restringir a trust policy da Role_Origem para permitir AssumeRole apenas pela conta especificada em `KiroAccountId`, usando a condição `aws:PrincipalAccount`
4. THE Template_Helper SHALL conceder à Role_Origem apenas permissões de leitura no S3 (`s3:ListBucket`, `s3:GetObject`) sem permissões de escrita
5. THE Gerenciador_STS SHALL gerar um `RoleSessionName` único por invocação Lambda, incluindo o nome da função Lambda para rastreabilidade em CloudTrail
6. WHEN credenciais temporárias forem obtidas, THE Gerenciador_STS SHALL utilizar as credenciais exclusivamente para criar o cliente S3, sem armazená-las em variáveis de ambiente ou logs

### Requisito 10: Target do Makefile para Deploy da Role na Conta de Origem

**User Story:** Como operador do sistema, eu quero um target no Makefile que faça deploy do template `source-account-role.yaml` na conta de origem, para que eu possa criar a Role_Origem de forma automatizada e obter o ARN da role para configurar o stack principal.

#### Critérios de Aceitação

1. THE Makefile SHALL definir um target `deploy-source-role` que execute `aws cloudformation deploy` com o template `source-account-role.yaml`
2. THE Target_Deploy_Role SHALL aceitar o parâmetro `SOURCE_ACCOUNT_PROFILE` para especificar o AWS CLI profile da Conta_Origem a ser usado via flag `--profile`
3. THE Target_Deploy_Role SHALL aceitar o parâmetro `KIRO_ACCOUNT_ID` para especificar o ID da conta AWS onde o Kiro Cost Analyzer está deployado
4. THE Target_Deploy_Role SHALL aceitar o parâmetro `SOURCE_BUCKET_NAME` para especificar o nome do bucket S3 de origem
5. THE Target_Deploy_Role SHALL aceitar o parâmetro opcional `KMS_KEY_ARN` com valor padrão vazio para cenários onde o bucket usa criptografia KMS CMK
6. IF os parâmetros `SOURCE_ACCOUNT_PROFILE`, `KIRO_ACCOUNT_ID` ou `SOURCE_BUCKET_NAME` não forem fornecidos, THEN THE Target_Deploy_Role SHALL exibir uma mensagem de erro listando os parâmetros obrigatórios e interromper a execução
7. WHEN o deploy do CloudFormation for bem-sucedido, THE Target_Deploy_Role SHALL consultar os outputs da stack e exibir o valor de `CrossAccountRoleArn` no terminal para facilitar a cópia do ARN para o parâmetro `SourceBucketRoleArn` do stack principal
8. THE Target_Deploy_Role SHALL passar os parâmetros `KiroAccountId`, `SourceBucketName` e `KMSKeyArn` como `--parameter-overrides` do `aws cloudformation deploy`
9. THE Target_Deploy_Role SHALL usar um nome de stack padrão `kiro-cross-account-role` configurável via parâmetro `SOURCE_ROLE_STACK_NAME`

### Requisito 11: Configuração do Role ARN via Interface Web

**User Story:** Como administrador do Kiro Cost Analyzer, eu quero poder visualizar e alterar o ARN da Role cross-account pela página de Settings da interface web, para que eu possa configurar ou remover o acesso cross-account sem precisar fazer redeploy do stack.

#### Critérios de Aceitação

1. THE `handle_get_config` SHALL retornar o campo `sourceBucketRoleArn` com o valor lido do SSM Parameter Store `/kiro-cost-analyzer/source-bucket-role-arn`
2. THE backend SHALL expor um endpoint `PUT /api/config/source-bucket-role-arn` que aceite um body JSON com o campo `sourceBucketRoleArn`
3. WHEN o endpoint `PUT /api/config/source-bucket-role-arn` receber um valor não-vazio, THE handler SHALL validar que o valor tem formato de ARN IAM válido (`arn:aws:iam::\d{12}:role/.+`) antes de salvar
4. IF o valor fornecido não tiver formato de ARN válido, THEN THE handler SHALL retornar status `error` com mensagem descritiva sem salvar no SSM
5. WHEN o valor for válido ou vazio, THE handler SHALL salvar o valor no SSM Parameter Store `/kiro-cost-analyzer/source-bucket-role-arn` via `ssm:PutParameter`
6. THE template.yaml SHALL passar a variável de ambiente `SSM_SOURCE_BUCKET_ROLE_ARN` com o caminho `/kiro-cost-analyzer/source-bucket-role-arn` para a `BackendFunction`
7. THE página de Settings do frontend SHALL exibir um campo editável para o `sourceBucketRoleArn` seguindo o mesmo padrão visual dos campos existentes (bucket name, prompts prefix, identity store ID)
8. THE página de Settings SHALL permitir limpar o campo `sourceBucketRoleArn` (salvar valor vazio) para desabilitar o modo cross-account
