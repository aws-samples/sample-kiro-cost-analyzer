# Documento de Design — Migração DynamoDB Single-Table Design

## Visão Geral

Este documento descreve o design técnico para migrar o backend analítico do Kiro Cost Analyzer de uma arquitetura Athena/Glue/Parquet para DynamoDB Single-Table Design (STD) com pipeline ETL orquestrado por AWS Step Functions.

A arquitetura atual sofre com:
- Alta latência: 6 queries sequenciais no Athena (~15-20s) na página de detalhes do usuário
- Memória ilimitada no Lambda ETL monolítico processando todos os arquivos em uma única invocação
- Scan ilimitado na ProcessedFilesTable
- Risco de perda de dados por sobrescrita de partições Parquet

A arquitetura alvo resolve esses problemas com:
- Uma única tabela DynamoDB (`Analytics_Table`) com latência de milissegundos para todas as consultas
- Step Functions orquestrando processamento paralelo de arquivos com controle de concorrência
- Contadores atômicos (`UpdateItem ADD`) para estatísticas pré-agregadas, eliminando condições de corrida
- Armazenamento híbrido de conteúdo de prompts (inline ≤4KB, S3 >4KB)

A stack será recriada do zero — não há necessidade de migração de dados históricos.

### Decisões de Design

1. **Single-Table Design vs Multi-Table**: STD foi escolhido porque todos os padrões de acesso são conhecidos e estáveis, e a co-localização de dados por `USER#{userId}` permite buscar todos os dados de um usuário em uma única Query.
2. **Step Functions vs SQS**: Step Functions foi escolhido pelo controle nativo de concorrência no Map state, visibilidade de execução, e Catch/Retry por item sem código adicional.
3. **Contadores atômicos vs BatchWriteItem**: `UpdateItem ADD` garante consistência em escritas concorrentes sem necessidade de locking ou transações.
4. **Armazenamento híbrido de prompts**: Inline para ≤4KB evita round-trip ao S3 na maioria dos casos; S3 para >4KB respeita o limite de 400KB do DynamoDB.
5. **On-demand billing**: PAY_PER_REQUEST elimina a necessidade de capacity planning para workloads imprevisíveis.
6. **Step Functions Standard vs Express**: Standard Workflow foi escolhido porque (a) o pipeline ETL pode exceder o limite de 5 minutos do Express ao processar centenas de arquivos em paralelo, (b) Standard oferece histórico completo de execução no console (input/output de cada estado) essencial para debug e observabilidade do pipeline, e (c) a frequência de execução é baixa (agendamento periódico), então o custo por transição de estado do Standard é negligível.

## Arquitetura

### Diagrama de Arquitetura de Alto Nível

```mermaid
graph TB
    subgraph "Frontend"
        SPA["React SPA<br/>(Cloudscape)"]
    end

    subgraph "API Layer"
        APIGW["API Gateway<br/>(Cognito JWT Auth)"]
        BACKEND["Backend Lambda<br/>(handlers → repository → DynamoDB)"]
    end

    subgraph "Storage"
        DDB_ANALYTICS["Analytics_Table<br/>(DynamoDB STD)"]
        DDB_PROCESSED["Processed_Files_Table<br/>(DynamoDB)"]
        DDB_USERNAMES["UserNames_Table<br/>(DynamoDB)"]
        S3_DATA["Data Bucket<br/>(prompts-content/)"]
        S3_SOURCE["Source Bucket<br/>(CSVs + .json.gz)"]
    end

    subgraph "ETL Pipeline"
        EB["EventBridge Rule<br/>(cron/rate)"]
        SFN["Step Functions<br/>(ETL_StateMachine)"]
        LIST_LAMBDA["ListFiles Lambda"]
        TASK_LAMBDA["Task Lambda<br/>(1 arquivo por invocação)"]
    end

    subgraph "Identity"
        COGNITO["Cognito User Pool"]
        IAM_IDC["IAM Identity Center"]
    end

    SPA -->|HTTPS| APIGW
    APIGW -->|JWT validation| COGNITO
    APIGW --> BACKEND
    BACKEND -->|Query/GetItem| DDB_ANALYTICS
    BACKEND -->|GetObject| S3_DATA

    EB -->|StartExecution| SFN
    BACKEND -->|"StartExecution (trigger manual)"| SFN
    SFN -->|Invoke| LIST_LAMBDA
    LIST_LAMBDA -->|ListObjects| S3_SOURCE
    LIST_LAMBDA -->|Scan| DDB_PROCESSED
    SFN -->|"Map state (paralelo)"| TASK_LAMBDA
    TASK_LAMBDA -->|GetObject| S3_SOURCE
    TASK_LAMBDA -->|"UpdateItem ADD / PutItem"| DDB_ANALYTICS
    TASK_LAMBDA -->|PutItem| DDB_PROCESSED
    TASK_LAMBDA -->|PutObject| S3_DATA
    TASK_LAMBDA -->|"GetItem / PutItem"| DDB_USERNAMES
    TASK_LAMBDA -->|DescribeUser| IAM_IDC

### Fluxo de Dados ETL (Step Functions)

```mermaid
stateDiagram-v2
    [*] --> ListFiles: StartExecution
    ListFiles --> CheckNewFiles
    CheckNewFiles --> RecordStatus_NoFiles: Nenhum arquivo novo
    CheckNewFiles --> ProcessFiles: Arquivos novos encontrados
    
    state ProcessFiles {
        [*] --> MapState
        state MapState <<fork>>
        MapState --> TaskLambda_1: arquivo_1
        MapState --> TaskLambda_2: arquivo_2
        MapState --> TaskLambda_N: arquivo_N
        
        state TaskLambda_1 {
            [*] --> Parse_1
            Parse_1 --> Normalize_1
            Normalize_1 --> ResolveNames_1
            ResolveNames_1 --> WriteDDB_1
            WriteDDB_1 --> MarkProcessed_1
        }
        
        TaskLambda_1 --> Join
        TaskLambda_2 --> Join
        TaskLambda_N --> Join
        state Join <<join>>
    }
    
    ProcessFiles --> RecordStatus
    RecordStatus_NoFiles --> [*]
    RecordStatus --> [*]
```

## Componentes e Interfaces

### 1. Schema DynamoDB — Analytics_Table

A tabela usa Single-Table Design com PK (String) e SK (String). Todos os tipos de entidade compartilham a mesma tabela, diferenciados por prefixos de PK e SK.

#### Tipos de Entidade e Padrões de Acesso

| Tipo de Entidade | PK | SK | Atributos | Padrão de Acesso |
|---|---|---|---|---|
| Metadados de Prompt | `USER#{userId}` | `PROMPT#{timestamp}#{requestId}` | modelId, triggerType, promptLength, responseLength, displayName, userName, region, accountId, conversationId, utteranceId, customizationArn, contentInS3, prompt?, response? | Query por usuário, ordenado por timestamp desc |
| Estatísticas Diárias | `USER#{userId}` | `STATS#DAILY#{date}` | totalCredits, overageCredits, totalMessages, totalConversations, totalInteractions | Query por usuário + range de datas |
| Distribuição por Modelo | `USER#{userId}` | `STATS#MODEL#{normalizedModelId}` | count, rawModelId | Query por usuário, prefix `STATS#MODEL#` |
| Distribuição por Trigger | `USER#{userId}` | `STATS#TRIGGER#{normalizedTriggerType}` | count, rawTriggerType | Query por usuário, prefix `STATS#TRIGGER#` |
| Agregados Globais Diários | `GLOBAL` | `STATS#DAILY#{date}` | totalCredits, overageCredits, totalMessages, totalConversations, totalUsers | Query com PK=GLOBAL + range de datas |

#### Exemplos de Itens

```json
// Metadados de Prompt (conteúdo inline ≤4KB)
{
  "PK": "USER#a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "SK": "PROMPT#2025-01-15T14:30:25Z#req-abc-123",
  "modelId": "anthropic.claude-sonnet-4-20250514-v1:0",
  "triggerType": "CHAT",
  "promptLength": 1200,
  "responseLength": 2800,
  "displayName": "João Silva",
  "userName": "joao.silva",
  "region": "us-east-1",
  "accountId": "673826570926",
  "conversationId": "conv-xyz",
  "utteranceId": "utt-456",
  "customizationArn": "",
  "contentInS3": false,
  "prompt": "Como faço para...",
  "response": "Para fazer isso, você pode..."
}

// Metadados de Prompt (conteúdo no S3 >4KB)
{
  "PK": "USER#a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "SK": "PROMPT#2025-01-15T15:00:00Z#req-def-456",
  "modelId": "anthropic.claude-sonnet-4-20250514-v1:0",
  "triggerType": "INLINE_CHAT",
  "promptLength": 8500,
  "responseLength": 12000,
  "contentInS3": true
}

// Estatísticas Diárias por Usuário
{
  "PK": "USER#a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "SK": "STATS#DAILY#2025-01-15",
  "totalCredits": 45.5,
  "overageCredits": 0.0,
  "totalMessages": 12,
  "totalConversations": 3,
  "totalInteractions": 28
}

// Distribuição por Modelo
{
  "PK": "USER#a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "SK": "STATS#MODEL#anthropic-claude-sonnet-4-20250514-v1-0",
  "count": 42,
  "rawModelId": "anthropic.claude-sonnet-4-20250514-v1:0"
}

// Distribuição por Trigger
{
  "PK": "USER#a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "SK": "STATS#TRIGGER#chat",
  "count": 35,
  "rawTriggerType": "CHAT"
}

// Agregados Globais Diários
{
  "PK": "GLOBAL",
  "SK": "STATS#DAILY#2025-01-15",
  "totalCredits": 1250.75,
  "overageCredits": 45.0,
  "totalMessages": 340,
  "totalConversations": 85,
  "totalUsers": 12
}
```

#### Padrões de Acesso Detalhados

| # | Operação API | Operação DynamoDB | PK | SK Condition | Notas |
|---|---|---|---|---|---|
| 1 | GET /api/usage/{userId}/details — uso diário | Query | `USER#{userId}` | `begins_with(SK, "STATS#DAILY#")` | Filtro between para range de datas |
| 2 | GET /api/usage/{userId}/details — distribuição modelo | Query | `USER#{userId}` | `begins_with(SK, "STATS#MODEL#")` | Retorna todos os modelos |
| 3 | GET /api/usage/{userId}/details — distribuição trigger | Query | `USER#{userId}` | `begins_with(SK, "STATS#TRIGGER#")` | Retorna todos os triggers |
| 4 | GET /api/usage/{userId}/details — prompts recentes | Query | `USER#{userId}` | `begins_with(SK, "PROMPT#")` | ScanIndexForward=False, Limit=20 |
| 5 | GET /api/usage — listagem de uso por usuário | Scan + agregação | — | `begins_with(SK, "STATS#DAILY#")` | Scan com FilterExpression; paginação via LastEvaluatedKey |
| 6 | GET /api/usage/account — agregados globais | Query | `GLOBAL` | `begins_with(SK, "STATS#DAILY#")` | Filtro between para range de datas |
| 7 | GET /api/prompts — listagem de prompts | Query | `USER#{userId}` | `begins_with(SK, "PROMPT#")` | Paginação com LastEvaluatedKey |
| 8 | GET /api/prompts/{requestId} — detalhe do prompt | Query | — | — | Precisa de GSI ou Scan; ver nota abaixo |
| 9 | ETL — escrita de prompt | PutItem | `USER#{userId}` | `PROMPT#{timestamp}#{requestId}` | Condicional: inline vs S3 |
| 10 | ETL — incremento stats diárias | UpdateItem ADD | `USER#{userId}` | `STATS#DAILY#{date}` | Atomic counter |
| 11 | ETL — incremento distribuição modelo | UpdateItem ADD | `USER#{userId}` | `STATS#MODEL#{normalizedModelId}` | Atomic counter |
| 12 | ETL — incremento distribuição trigger | UpdateItem ADD | `USER#{userId}` | `STATS#TRIGGER#{normalizedTriggerType}` | Atomic counter |
| 13 | ETL — incremento agregados globais | UpdateItem ADD | `GLOBAL` | `STATS#DAILY#{date}` | Atomic counter |

**Nota sobre GET /api/prompts/{requestId}**: Este endpoint busca um prompt por `requestId` sem conhecer o `userId`. Para suportar esse padrão sem Scan, será adicionado um Global Secondary Index (GSI) com:
- GSI PK: `requestId`
- GSI SK: (não necessário, pode ser omitido)
- Projeção: ALL

Isso permite buscar qualquer prompt por `requestId` com uma Query no GSI.

**Nota sobre GET /api/usage (Scan)**: A listagem de uso por usuário requer agregar estatísticas de todos os usuários. Como não há uma partition key que agrupe todos os usuários, será necessário um Scan com FilterExpression `begins_with(SK, "STATS#DAILY#")`. Para mitigar o custo:
- Paginação com `limit` (máximo 50) e `nextToken` (LastEvaluatedKey)
- O Scan é aceitável porque a tabela terá volume moderado (centenas de usuários, não milhões)
- Alternativa futura: manter um item `GLOBAL#USERS` com lista de userIds ativos para fazer Queries paralelas

### 2. SK Normalizer — Módulo de Normalização de Sort Keys

O SK_Normalizer é um módulo Python independente (`shared/sk_normalizer.py`) importável tanto pela Task_Lambda quanto pelo Backend_API.

#### Algoritmo de Normalização

```python
def normalize_sk_value(raw_value: str, canonical_map: dict[str, str] | None = None) -> str:
    """
    Transforma um valor bruto em slug compatível com DynamoDB SK.
    
    Pipeline de transformações (em sequência):
    1. Lookup no dicionário canônico (se fornecido e valor encontrado)
    2. Converter para lowercase
    3. Trim (remover espaços nas extremidades)
    4. Substituir espaços e caracteres especiais por hífens
    5. Remover caracteres não alfanuméricos exceto hífens
    6. Colapsar hífens consecutivos em um único hífen
    7. Remover hífens no início e final
    8. Truncar para máximo 128 caracteres
    """
```

#### Exemplos de Normalização

| Entrada | Saída |
|---|---|
| `anthropic.claude-sonnet-4-20250514-v1:0` | `anthropic-claude-sonnet-4-20250514-v1-0` |
| `CHAT` | `chat` |
| `INLINE_CHAT` | `inline-chat` |
| `Claude Opus 2.6M bla bla` | `claude-opus-2-6m-bla-bla` |
| `  spaces  around  ` | `spaces-around` |
| `special!@#chars$%^` | `special-chars` |

#### Dicionário Canônico

O módulo suporta um dicionário de mapeamentos canônicos carregado de variável de ambiente `SK_CANONICAL_MAP` (JSON string) ou arquivo de configuração. Exemplo:

```json
{
  "anthropic.claude-sonnet-4-20250514-v1:0": "claude-sonnet-4",
  "anthropic.claude-haiku-3-20250514-v1:0": "claude-haiku-3"
}
```

Se o valor bruto for encontrado no dicionário, o valor canônico é usado como entrada para o pipeline de slug-ificação. Isso permite agrupar variantes de modelo sob um nome canônico sem alterar código.

### 3. Step Functions — ETL_StateMachine (ASL — Standard Workflow)

A state machine usa o tipo **Standard** (não Express) para suportar execuções longas e histórico completo de execução.

```yaml
Comment: "ETL Pipeline - processa arquivos S3 em paralelo (Standard Workflow)"
StartAt: ListNewFiles
States:

  ListNewFiles:
    Type: Task
    Resource: "${ListFilesLambdaArn}"
    ResultPath: "$.listResult"
    Next: CheckNewFiles
    Retry:
      - ErrorEquals: ["States.TaskFailed"]
        IntervalSeconds: 5
        MaxAttempts: 2
        BackoffRate: 2.0

  CheckNewFiles:
    Type: Choice
    Choices:
      - Variable: "$.listResult.newFilesCount"
        NumericGreaterThan: 0
        Next: ProcessFiles
    Default: RecordStatusNoFiles

  RecordStatusNoFiles:
    Type: Task
    Resource: "arn:aws:states:::dynamodb:putItem"
    Parameters:
      TableName: "${AnalyticsTableName}"
      Item:
        PK:
          S: "ETL_STATUS"
        SK:
          S.$: "States.Format('EXEC#{}', $$.Execution.Name)"
        status:
          S: "SUCCESS"
        filesProcessed:
          N: "0"
        recordsWritten:
          N: "0"
        timestamp:
          S.$: "$$.State.EnteredTime"
        executionArn:
          S.$: "$$.Execution.Id"
    End: true

  ProcessFiles:
    Type: Map
    ItemsPath: "$.listResult.newFiles"
    MaxConcurrency: 10
    ItemProcessor:
      ProcessorConfig:
        Mode: INLINE
      StartAt: ParseAndNormalize
      States:

        # Lambda: ler S3, parse, normalizar, resolver nomes
        ParseAndNormalize:
          Type: Task
          Resource: "${ParseLambdaArn}"
          Parameters:
            bucket.$: "$.bucket"
            key.$: "$.key"
            fileType.$: "$.fileType"
            correlationId.$: "$$.Execution.Id"
          ResultPath: "$.parseResult"
          Next: WriteToDynamoDB
          Retry:
            - ErrorEquals: ["Lambda.ServiceException", "Lambda.TooManyRequestsException"]
              IntervalSeconds: 2
              MaxAttempts: 3
              BackoffRate: 2.0
          Catch:
            - ErrorEquals: ["States.ALL"]
              ResultPath: "$.error"
              Next: RecordFileError

        # Lambda: escrever no DynamoDB + S3
        WriteToDynamoDB:
          Type: Task
          Resource: "${WriterLambdaArn}"
          Parameters:
            records.$: "$.parseResult.records"
            fileType.$: "$.fileType"
            key.$: "$.key"
            correlationId.$: "$$.Execution.Id"
          ResultPath: "$.writeResult"
          Next: MarkFileProcessed
          Retry:
            - ErrorEquals: ["DynamoDB.ProvisionedThroughputExceededException", "Lambda.ServiceException"]
              IntervalSeconds: 2
              MaxAttempts: 3
              BackoffRate: 2.0
          Catch:
            - ErrorEquals: ["States.ALL"]
              ResultPath: "$.error"
              Next: RecordFileError

        # Integracao nativa Step Functions -> DynamoDB (sem Lambda)
        MarkFileProcessed:
          Type: Task
          Resource: "arn:aws:states:::dynamodb:putItem"
          Parameters:
            TableName: "${ProcessedFilesTableName}"
            Item:
              fileKey:
                S.$: "$.key"
              processedAt:
                S.$: "$$.State.EnteredTime"
              recordCount:
                N.$: "States.JsonToString($.writeResult.recordCount)"
              status:
                S: "SUCCESS"
              errorMessage:
                S: ""
          ResultPath: "$.markResult"
          End: true
          Catch:
            - ErrorEquals: ["States.ALL"]
              ResultPath: "$.error"
              Next: RecordFileError

        RecordFileError:
          Type: Pass
          Parameters:
            status: "ERROR"
            key.$: "$.key"
            error.$: "$.error"
          End: true

    ResultPath: "$.mapResults"
    Next: RecordStatus

  RecordStatus:
    Type: Task
    Resource: "${RecordStatusLambdaArn}"
    Parameters:
      executionId.$: "$$.Execution.Id"
      listResult.$: "$.listResult"
      mapResults.$: "$.mapResults"
    End: true
```

#### Componentes da State Machine

1. **ListNewFiles Lambda**: Lista arquivos S3 (CSVs + .json.gz), consulta ProcessedFilesTable, retorna lista de arquivos novos com metadados (bucket, key, fileType).
2. **ProcessFiles Map State**: Processa cada arquivo em paralelo (MaxConcurrency=10). Cada iteração passa por 3 estados sequenciais dentro do Map.
3. **ParseAndNormalize Lambda** (Parse Lambda): Lê o arquivo do S3, faz parse (CSV ou .json.gz), normaliza registros, resolve nomes de usuário. Retorna registros prontos para escrita. Responsabilidade: leitura + transformação.
4. **WriteToDynamoDB Lambda** (Writer Lambda): Recebe registros normalizados e escreve na Analytics_Table (PutItem para prompts, UpdateItem ADD para contadores, PutObject no S3 para conteúdo grande). Responsabilidade: persistência.
5. **MarkFileProcessed** (Integração nativa DynamoDB): Estado Task usando `arn:aws:states:::dynamodb:putItem` — marca o arquivo como processado diretamente pelo Step Functions, sem Lambda.
6. **RecordStatusNoFiles** (Integração nativa DynamoDB): Quando não há arquivos novos, registra status diretamente no DynamoDB via integração nativa, sem invocar Lambda.
7. **RecordStatus Lambda**: Registra o sumário completo da execução no SSM Parameter Store (precisa de Lambda porque SSM PutParameter não é suportado como integração nativa do Step Functions).

### 4. Organização do Código — Backend API

```
backend/
├── __init__.py
├── handler.py                    # Entry point — roteamento HTTP (existente, adaptado)
├── handlers/
│   ├── __init__.py
│   ├── usage_handler.py          # GET /api/usage
│   ├── account_usage_handler.py  # GET /api/usage/account
│   ├── user_details_handler.py   # GET /api/usage/{userId}/details
│   ├── prompts_handler.py        # GET /api/prompts, GET /api/prompts/{requestId}
│   ├── export_handler.py         # GET /api/usage/export
│   ├── config_handler.py         # GET/PUT /api/config/*
│   ├── etl_trigger_handler.py    # POST /api/etl/trigger
│   └── users_handler.py          # GET/POST/DELETE /api/users
├── repository/
│   ├── __init__.py
│   └── analytics_repository.py   # Encapsula todos os acessos à Analytics_Table
├── models/
│   ├── __init__.py
│   └── types.py                  # Dataclasses: UserStats, PromptMetadata, GlobalStats, etc.
└── utils/
    ├── __init__.py
    ├── sk_normalizer.py           # Symlink ou cópia do shared/sk_normalizer.py
    └── logging.py                 # Configuração de logs estruturados JSON
```

#### Repository Layer — Interface

```python
class AnalyticsRepository:
    def __init__(self, table_name: str, dynamodb_resource=None):
        """Injeção de dependência do recurso DynamoDB para testabilidade."""
    
    # --- Leitura por Usuário ---
    def get_user_daily_stats(self, user_id: str, start_date: str = None, end_date: str = None) -> list[dict]:
        """Query STATS#DAILY# para um usuário, com filtro opcional de datas."""
    
    def get_user_model_distribution(self, user_id: str) -> list[dict]:
        """Query STATS#MODEL# para um usuário."""
    
    def get_user_trigger_distribution(self, user_id: str) -> list[dict]:
        """Query STATS#TRIGGER# para um usuário."""
    
    def get_user_prompts(self, user_id: str, limit: int = 20, start_date: str = None, 
                         end_date: str = None, scan_forward: bool = False) -> dict:
        """Query PROMPT# para um usuário, com paginação e filtro de datas."""
    
    # --- Leitura Global ---
    def get_global_daily_stats(self, start_date: str = None, end_date: str = None) -> list[dict]:
        """Query GLOBAL / STATS#DAILY# com filtro de datas."""
    
    # --- Leitura por requestId (via GSI) ---
    def get_prompt_by_request_id(self, request_id: str) -> dict | None:
        """Query no GSI requestId-index."""
    
    # --- Scan para listagem de uso ---
    def scan_user_stats(self, limit: int = 50, next_token: str = None, 
                        subscription_tier: str = None) -> dict:
        """Scan com FilterExpression para agregar stats por usuário."""
```

### 5. Organização do Código — ETL (Task_Lambda)

```
etl/
├── __init__.py
├── parse_handler.py              # Entry point da Parse Lambda (lê S3, parse, normaliza, resolve nomes)
├── writer_handler.py             # Entry point da Writer Lambda (escreve no DynamoDB + S3)
├── list_handler.py               # Entry point da ListFiles Lambda
├── record_status_handler.py      # Entry point da RecordStatus Lambda
├── processors/
│   ├── __init__.py
│   ├── csv_processor.py          # Parse + normalização de CSVs de atividade
│   └── prompt_processor.py       # Parse + normalização de .json.gz de prompts
├── repository/
│   ├── __init__.py
│   └── analytics_writer.py       # Escritas na Analytics_Table (PutItem, UpdateItem ADD)
├── utils/
│   ├── __init__.py
│   ├── sk_normalizer.py          # Symlink ou cópia do shared/sk_normalizer.py
│   ├── name_resolver.py          # Resolução de nomes via UserNamesTable + Identity Center
│   ├── logging.py                # Configuração de logs estruturados JSON
│   └── s3_reader.py              # Leitura de arquivos S3
├── config.py                     # Configuração via variáveis de ambiente
└── requirements.txt
```

#### Parse Lambda — Fluxo de Processamento

```python
def parse_handler(event, context):
    """
    Evento recebido do Step Functions:
    {
        "bucket": "source-bucket",
        "key": "activities/AWSLogs/.../file.csv",
        "fileType": "csv" | "prompt",
        "correlationId": "arn:aws:states:..."
    }
    Responsabilidade: leitura + transformação (sem escrita no DDB).
    """
    # 1. Configurar logger com correlationId
    # 2. Ler arquivo do S3
    # 3. Despachar para processor correto (csv_processor ou prompt_processor)
    # 4. Processor retorna registros normalizados
    # 5. Resolver nomes de usuário (cache DynamoDB + Identity Center)
    # 6. Retornar registros normalizados prontos para escrita
```

#### Writer Lambda — Fluxo de Persistência

```python
def writer_handler(event, context):
    """
    Evento recebido do Step Functions:
    {
        "records": [...],
        "fileType": "csv" | "prompt",
        "key": "...",
        "correlationId": "arn:aws:states:..."
    }
    Responsabilidade: persistência (DynamoDB + S3).
    """
    # 1. Configurar logger com correlationId
    # 2. Para cada registro: escrever na Analytics_Table via analytics_writer
    #    - PutItem para metadados de prompt
    #    - UpdateItem ADD para contadores (stats diárias, modelo, trigger, global)
    #    - PutObject no S3 para conteúdo grande (>4KB)
    # 3. Retornar resultado (recordCount, itemsWritten, durationMs)
```

#### Analytics Writer — Operações de Escrita

```python
class AnalyticsWriter:
    def __init__(self, table_name: str, data_bucket: str, dynamodb_resource=None, s3_client=None):
        """Injeção de dependência para testabilidade."""
    
    def write_prompt(self, user_id: str, prompt_record: dict, prompt_content: str, response_content: str):
        """PutItem para metadados de prompt. Decide inline vs S3 baseado no tamanho."""
    
    def increment_daily_stats(self, user_id: str, date: str, credits: float, 
                               overage: float, messages: int, conversations: int, interactions: int):
        """UpdateItem ADD para STATS#DAILY#{date}."""
    
    def increment_model_count(self, user_id: str, normalized_model_id: str, raw_model_id: str):
        """UpdateItem ADD para STATS#MODEL#{normalizedModelId}. SET rawModelId if_not_exists."""
    
    def increment_trigger_count(self, user_id: str, normalized_trigger: str, raw_trigger: str):
        """UpdateItem ADD para STATS#TRIGGER#{normalizedTriggerType}. SET rawTriggerType if_not_exists."""
    
    def increment_global_daily_stats(self, date: str, credits: float, overage: float,
                                      messages: int, conversations: int, user_ids: set[str]):
        """UpdateItem ADD para GLOBAL / STATS#DAILY#{date}. ADD totalUsers com set de userIds."""
```

### 6. Logging Estruturado

Todas as Lambdas emitirão logs em formato JSON estruturado usando um módulo utilitário compartilhado.

#### Formato de Log

```json
{
  "timestamp": "2025-01-15T14:30:25.123Z",
  "level": "INFO",
  "message": "Arquivo processado com sucesso",
  "correlationId": "arn:aws:states:us-east-1:123456789012:execution:etl-state-machine:exec-abc",
  "s3Key": "activities/AWSLogs/673826570926/KiroLogs/user_report/2025/01/file.csv",
  "fileType": "csv",
  "recordCount": 45,
  "itemsWritten": 52,
  "durationMs": 1234,
  "lambda": "task-lambda",
  "requestId": "lambda-request-id"
}
```

#### Campos Padrão

| Campo | Descrição | Presente em |
|---|---|---|
| `timestamp` | ISO 8601 com milissegundos | Todos os logs |
| `level` | INFO, WARNING, ERROR | Todos os logs |
| `message` | Mensagem descritiva | Todos os logs |
| `correlationId` | Execution ARN do Step Functions | Task_Lambda, ListFiles Lambda |
| `s3Key` | Chave S3 do arquivo sendo processado | Task_Lambda |
| `fileType` | `csv` ou `prompt` | Task_Lambda |
| `recordCount` | Quantidade de registros processados | Task_Lambda (conclusão) |
| `itemsWritten` | Quantidade de itens escritos no DDB | Task_Lambda (conclusão) |
| `durationMs` | Duração do processamento em ms | Task_Lambda (conclusão) |
| `errorType` | Tipo da exceção | Logs de erro |
| `errorMessage` | Mensagem de erro completa | Logs de erro |
| `stackTrace` | Stack trace completo | Logs de erro |
| `endpoint` | Path do endpoint chamado | Backend_API |
| `queryDurationMs` | Duração da query DynamoDB em ms | Backend_API |
| `itemCount` | Quantidade de itens retornados | Backend_API |

#### Implementação

```python
import json
import logging
import time
from datetime import datetime, timezone

class StructuredLogger:
    def __init__(self, lambda_name: str, correlation_id: str = ""):
        self.lambda_name = lambda_name
        self.correlation_id = correlation_id
        self._logger = logging.getLogger(lambda_name)
    
    def _emit(self, level: str, message: str, **kwargs):
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": level,
            "message": message,
            "lambda": self.lambda_name,
            "correlationId": self.correlation_id,
            **kwargs
        }
        print(json.dumps(entry, default=str))
    
    def info(self, message: str, **kwargs):
        self._emit("INFO", message, **kwargs)
    
    def error(self, message: str, **kwargs):
        self._emit("ERROR", message, **kwargs)
    
    def warning(self, message: str, **kwargs):
        self._emit("WARNING", message, **kwargs)
```

### 7. Alterações no Template SAM

#### Recursos a Adicionar

1. **Analytics_Table** (`AWS::DynamoDB::Table`): PK/SK String, PAY_PER_REQUEST, GSI `requestId-index`
2. **ETL_StateMachine** (`AWS::Serverless::StateMachine`): Tipo Standard, definição ASL em YAML, role com permissão para invocar Lambdas e acessar DynamoDB
3. **ListFilesFunction** (`AWS::Serverless::Function`): Lambda para listar arquivos novos
4. **ParseFunction** (`AWS::Serverless::Function`): Lambda para ler, parsear e normalizar um arquivo (sem escrita no DDB)
5. **WriterFunction** (`AWS::Serverless::Function`): Lambda para escrever registros normalizados no DynamoDB e S3
6. **RecordStatusFunction** (`AWS::Serverless::Function`): Lambda para registrar status da execução no SSM
7. **EventBridge Rule**: ScheduleV2 como evento da StateMachine

#### Recursos a Remover

1. `GlueDatabase`, `GlueActivityTable`, `GluePromptsTable`
2. `AthenaWorkgroup`
3. `LakeFormationSetupFunction`, `LakeFormationSetup`
4. Todas as `AWS::LakeFormation::Permissions`
5. Variáveis de ambiente Athena/Glue do BackendFunction
6. Políticas IAM de Athena/Glue do BackendFunction e EtlFunction

#### Permissões IAM

| Lambda | Recurso | Ações |
|---|---|---|
| ParseFunction | Source Bucket | GetObject |
| ParseFunction | UserNamesTable | GetItem, PutItem |
| ParseFunction | Identity Center | DescribeUser |
| ParseFunction | SSM Parameters | GetParameter |
| WriterFunction | Analytics_Table | PutItem, UpdateItem, GetItem |
| WriterFunction | Data Bucket | PutObject |
| WriterFunction | SSM Parameters | GetParameter |
| ListFilesFunction | Source Bucket | ListBucket |
| ListFilesFunction | ProcessedFilesTable | Scan |
| ListFilesFunction | SSM Parameters | GetParameter |
| RecordStatusFunction | SSM Parameters | PutParameter |
| BackendFunction | Analytics_Table | Query, GetItem, Scan |
| BackendFunction | Data Bucket | GetObject |
| ETL_StateMachine | ParseFunction | lambda:InvokeFunction |
| ETL_StateMachine | WriterFunction | lambda:InvokeFunction |
| ETL_StateMachine | ListFilesFunction | lambda:InvokeFunction |
| ETL_StateMachine | RecordStatusFunction | lambda:InvokeFunction |
| ETL_StateMachine | ProcessedFilesTable | PutItem |
| ETL_StateMachine | Analytics_Table | PutItem |

## Modelos de Dados

### Backend — Dataclasses

```python
@dataclass
class PromptMetadata:
    userId: str
    timestamp: str
    requestId: str
    modelId: str
    triggerType: str
    promptLength: int
    responseLength: int
    displayName: str = ""
    userName: str = ""
    originalUserId: str = ""
    date: str = ""
    hour: str = ""
    region: str = ""
    accountId: str = ""
    conversationId: str = ""
    utteranceId: str = ""
    customizationArn: str = ""
    contentInS3: bool = False
    prompt: str | None = None      # Presente apenas se inline
    response: str | None = None    # Presente apenas se inline

@dataclass
class DailyStats:
    date: str
    totalCredits: float
    overageCredits: float
    totalMessages: int
    totalConversations: int
    totalInteractions: int

@dataclass
class ModelDistribution:
    modelId: str           # rawModelId (valor original)
    normalizedModelId: str # slug normalizado
    count: int

@dataclass
class TriggerDistribution:
    triggerType: str           # rawTriggerType (valor original)
    normalizedTriggerType: str # slug normalizado
    count: int

@dataclass
class GlobalDailyStats:
    date: str
    totalCredits: float
    overageCredits: float
    totalMessages: int
    totalConversations: int
    totalUsers: int
```

### ETL — Evento da Task_Lambda

```python
@dataclass
class TaskEvent:
    bucket: str
    key: str
    fileType: str        # "csv" | "prompt"
    correlationId: str   # Execution ARN do Step Functions

@dataclass
class TaskResult:
    status: str          # "SUCCESS" | "ERROR"
    key: str
    recordCount: int
    itemsWritten: int
    durationMs: int
    errorMessage: str = ""
```

## Propriedades de Corretude

*Uma propriedade é uma característica ou comportamento que deve ser verdadeiro em todas as execuções válidas de um sistema — essencialmente, uma declaração formal sobre o que o sistema deve fazer. Propriedades servem como ponte entre especificações legíveis por humanos e garantias de corretude verificáveis por máquina.*

### Propriedade 1: Invariantes de saída do SK Normalizer

*Para qualquer* string de entrada (incluindo strings vazias, strings com apenas espaços, strings com caracteres especiais Unicode, e strings muito longas), a saída do `normalize_sk_value` DEVE satisfazer todas as seguintes condições simultaneamente: (a) conter apenas caracteres lowercase alfanuméricos e hífens, (b) não começar nem terminar com hífen, (c) não conter hífens consecutivos, (d) ter comprimento máximo de 128 caracteres, e (e) para entradas que contenham pelo menos um caractere alfanumérico, a saída DEVE ser não-vazia.

**Valida: Requisitos 2.1, 2.2, 2.6**

### Propriedade 2: Determinismo e idempotência do SK Normalizer

*Para qualquer* string de entrada, (a) chamar `normalize_sk_value` duas vezes com a mesma entrada DEVE produzir resultados idênticos (determinismo), e (b) aplicar `normalize_sk_value` ao resultado de uma normalização anterior DEVE produzir o mesmo resultado (idempotência: `normalize(normalize(x)) == normalize(x)`).

**Valida: Requisitos 2.3, 2.8**

### Propriedade 3: Mapeamento canônico do SK Normalizer

*Para qualquer* dicionário canônico e qualquer valor de entrada que seja uma chave do dicionário, a saída de `normalize_sk_value(input, canonical_map)` DEVE ser igual a `normalize_sk_value(canonical_map[input])`. Para entradas que NÃO são chaves do dicionário, a saída DEVE ser igual a `normalize_sk_value(input)` sem o dicionário.

**Valida: Requisito 2.5**

### Propriedade 4: Preservação de valores originais nas escritas

*Para qualquer* valor bruto de modelId ou triggerType, quando o `AnalyticsWriter` escrever um item de distribuição na Analytics_Table, o item resultante DEVE conter tanto o valor normalizado como componente da SK quanto o valor original bruto no atributo `rawModelId` ou `rawTriggerType`.

**Valida: Requisito 2.4**

### Propriedade 5: Acumulação correta de contadores atômicos

*Para qualquer* sequência de N registros de atividade/prompts pertencentes ao mesmo usuário e mesma data, após processar todos os registros via `AnalyticsWriter`, os valores dos contadores no item `STATS#DAILY#{date}` DEVEM ser iguais à soma dos valores individuais de cada registro. O mesmo DEVE valer para contadores de distribuição por modelo (`STATS#MODEL#`), por trigger (`STATS#TRIGGER#`) e agregados globais (`GLOBAL` / `STATS#DAILY#`).

**Valida: Requisitos 4.3, 4.4, 4.5, 4.6**

### Propriedade 6: Decisão de armazenamento híbrido baseada no tamanho do conteúdo

*Para qualquer* prompt com conteúdo (texto do prompt + resposta), se o tamanho combinado for ≤ 4KB, o item na Analytics_Table DEVE ter `contentInS3=false` e conter os campos `prompt` e `response` inline. Se o tamanho combinado for > 4KB, o item DEVE ter `contentInS3=true` e o conteúdo DEVE estar armazenado no S3 em `prompts-content/{requestId}.json`.

**Valida: Requisitos 4.7, 4.8**

### Propriedade 7: Extração de UUID de userId com prefixo de diretório

*Para qualquer* string no formato `d-{directoryId}.{uuid}` onde `directoryId` é uma string alfanumérica e `uuid` é um UUID válido, `extract_uuid` DEVE retornar a porção `{uuid}`. Para strings que não contêm `.`, DEVE retornar a string original inalterada.

**Valida: Requisito 5.3**

### Propriedade 8: Consistência de recuperação de conteúdo de prompts

*Para qualquer* prompt armazenado na Analytics_Table, quando o Backend_API buscar o detalhe via GET /api/prompts/{requestId}: se `contentInS3` for `true`, o conteúdo DEVE ser buscado do S3; se `contentInS3` for `false`, o conteúdo DEVE ser retornado diretamente do item do DynamoDB. Em ambos os casos, o conteúdo retornado DEVE ser idêntico ao conteúdo original escrito pela Task_Lambda.

**Valida: Requisitos 8.4, 8.5**

### Propriedade 9: Completude da paginação

*Para qualquer* conjunto de dados e tamanho de página (limit), iterar por todas as páginas usando nextToken DEVE retornar todos os itens exatamente uma vez, sem duplicatas e sem omissões. A união de todas as páginas DEVE ser igual ao conjunto completo de itens que satisfazem os filtros da consulta.

**Valida: Requisitos 6.4, 8.3**

### Propriedade 10: Preservação de totais na agregação de timeline

*Para qualquer* conjunto de estatísticas diárias globais e qualquer granularidade (dia, semana, mês), a soma dos valores de `totalCredits`, `totalMessages` e `totalConversations` na timeline agrupada DEVE ser igual à soma dos mesmos valores nas estatísticas diárias individuais.

**Valida: Requisito 9.3**

## Tratamento de Erros

### Task_Lambda

| Cenário | Comportamento | Resultado |
|---|---|---|
| Arquivo S3 não encontrado | Lançar exceção `FileNotFoundError` | Step Functions captura via Catch, continua com próximo arquivo |
| CSV com formato inválido | Lançar exceção `ValueError` | Step Functions captura via Catch |
| .json.gz corrompido | Lançar exceção `ValueError` | Step Functions captura via Catch |
| DynamoDB throttling | Retry com backoff exponencial (3 tentativas) | Se persistir, lançar exceção |
| Identity Center indisponível | Log warning, continuar sem nome resolvido | displayName/userName ficam vazios |
| S3 write failure (prompt content) | Lançar exceção | Step Functions captura via Catch |
| Arquivo já processado | Verificar ProcessedFilesTable antes de processar, skip se já existe | Retornar resultado com recordCount=0 |

### Backend_API

| Cenário | HTTP Status | Resposta |
|---|---|---|
| userId não encontrado | 404 | `{"error": "NotFound", "message": "Nenhum dado encontrado para o userId '...'"}` |
| requestId não encontrado | 404 | `{"error": "NotFound", "message": "Prompt com requestId '...' não encontrado"}` |
| DynamoDB throttling | 503 | `{"error": "ServiceUnavailable", "message": "Serviço temporariamente indisponível. Tente novamente."}` |
| Parâmetros inválidos | 400 | `{"error": "InvalidParameters", "message": "..."}` |
| Erro interno | 500 | `{"error": "InternalError", "message": "Erro interno do servidor."}` |
| Acesso não autorizado | 403 | `{"error": "Forbidden", "message": "Acesso restrito a administradores"}` |

### Step Functions

| Cenário | Comportamento |
|---|---|
| ListFiles Lambda falha | Retry 2x com backoff. Se persistir, execução falha. |
| Task_Lambda falha para um arquivo | Catch captura erro, Map continua com próximos arquivos. Erro registrado no resultado. |
| Task_Lambda timeout | Catch captura `States.Timeout`, Map continua. |
| Todas as Task_Lambda falham | Map completa com todos os erros. RecordStatus registra status ERROR. |
| RecordStatus Lambda falha | Execução falha. Status não registrado (monitorar via Step Functions console). |

## Estratégia de Testes

### Testes Unitários

Testes unitários com `pytest` e `moto` (mock AWS) para:

1. **SK Normalizer**: Testes de exemplos específicos (caracteres especiais, strings vazias, strings longas, dicionário canônico)
2. **AnalyticsRepository**: Testes com DynamoDB local/moto verificando queries, filtros de data, paginação
3. **AnalyticsWriter**: Testes com DynamoDB local/moto verificando PutItem, UpdateItem ADD, decisão inline vs S3
4. **Handlers**: Testes com repository mockado verificando roteamento, validação de parâmetros, formatação de resposta
5. **CSV Processor**: Testes de parse e normalização com CSVs de exemplo
6. **Prompt Processor**: Testes de parse e normalização com .json.gz de exemplo
7. **StructuredLogger**: Testes verificando formato JSON e campos obrigatórios

### Testes de Propriedade (Property-Based Testing)

Biblioteca: `hypothesis` (Python)

Cada teste de propriedade DEVE:
- Executar no mínimo 100 iterações (`@settings(max_examples=100)`)
- Referenciar a propriedade do documento de design via tag no docstring
- Usar geradores (`@given`) apropriados para o domínio

Propriedades a implementar:
- **Propriedade 1**: SK Normalizer output invariants — `@given(st.text())` → verificar regex, comprimento, sem hífens consecutivos
- **Propriedade 2**: SK Normalizer determinism/idempotence — `@given(st.text())` → `normalize(x) == normalize(x)` e `normalize(normalize(x)) == normalize(x)`
- **Propriedade 3**: Canonical map — `@given(st.dictionaries(st.text(), st.text()), st.text())` → verificar comportamento com e sem match
- **Propriedade 4**: Raw value preservation — `@given(st.text())` → verificar item contém rawModelId/rawTriggerType
- **Propriedade 5**: Atomic counter accumulation — `@given(st.lists(st.floats(min_value=0, max_value=1000)))` → soma dos incrementos == valor final
- **Propriedade 6**: Hybrid storage decision — `@given(st.text(min_size=0, max_size=10000))` → contentInS3 iff len > 4096
- **Propriedade 7**: UUID extraction — `@given(st.text(), st.uuids())` → extract_uuid("d-{x}.{uuid}") == str(uuid)
- **Propriedade 8**: Content retrieval consistency — round-trip: write → read deve retornar conteúdo idêntico
- **Propriedade 9**: Pagination completeness — `@given(st.lists(st.text()))` → union of all pages == full dataset
- **Propriedade 10**: Timeline aggregation — `@given(st.lists(st.tuples(st.dates(), st.floats())))` → sum(grouped) == sum(individual)

Tag format: `Feature: dynamodb-sdt-migration, Property {N}: {título}`

### Testes de Integração

1. **ETL Pipeline end-to-end**: Executar Step Functions com arquivos de teste no S3, verificar itens na Analytics_Table
2. **Backend API end-to-end**: Chamar endpoints via API Gateway, verificar respostas
3. **Compatibilidade de resposta**: Comparar schemas de resposta com interfaces TypeScript do frontend
