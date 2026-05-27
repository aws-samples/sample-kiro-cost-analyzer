# Documento de Requisitos

## Introdução

Migração do backend analítico do Kiro Cost Analyzer de uma arquitetura baseada em Athena/Glue/Parquet para um DynamoDB Single-Table Design (STD) com pipeline ETL orquestrado por AWS Step Functions. O sistema atual sofre com alta latência de consultas (6 queries sequenciais no Athena na página de detalhes do usuário, ~15-20s), acúmulo ilimitado de memória no Lambda ETL monolítico, Scan ilimitado no DynamoDB para rastreamento de arquivos processados, e risco de perda de dados por sobrescrita de partições Parquet. A arquitetura alvo substitui Athena/Glue/Lake Formation/Parquet por uma única tabela DynamoDB para todas as consultas do dashboard, substitui o ETL monolítico por uma State Machine do Step Functions que orquestra o processamento paralelo de arquivos com controle de concorrência, e utiliza contadores atômicos para estatísticas pré-agregadas. A stack será recriada do zero ao final do desenvolvimento, dispensando migração de dados históricos.

## Glossário

- **Analytics_Table**: A tabela única do DynamoDB que armazena todos os dados do dashboard usando padrões de acesso Single-Table Design (metadados de prompts, estatísticas diárias, distribuições por modelo/trigger, agregados globais)
- **ETL_StateMachine**: A State Machine do AWS Step Functions que orquestra o pipeline ETL — lista arquivos novos, processa cada arquivo em paralelo via estado Map (com controle de concorrência), e registra o status da execução ao final
- **Task_Lambda**: A função Lambda invocada como tarefa do Step Functions que processa um único arquivo S3 (CSV ou .json.gz) e escreve os resultados na Analytics_Table. Projetada para ser invocada concorrentemente por múltiplas execuções paralelas do estado Map sem estado mutável compartilhado
- **STD**: Single-Table Design — um padrão do DynamoDB onde múltiplos tipos de entidade compartilham uma tabela, diferenciados por prefixos de partition key (PK) e sort key (SK)
- **Atomic_Counter**: Uma operação UpdateItem do DynamoDB usando expressão ADD para incrementar atributos numéricos atomicamente sem necessidade de leitura prévia
- **Prompt_Content**: O texto completo de um prompt e sua resposta, armazenado inline no item da Analytics_Table (quando menor que 4KB) ou no S3 em `prompts-content/{requestId}.json` (quando maior que 4KB)
- **Backend_API**: A função Lambda do API Gateway que serve dados do dashboard consultando a Analytics_Table
- **Processed_Files_Table**: A tabela DynamoDB existente que rastreia quais arquivos S3 já foram processados pelo pipeline ETL
- **SK_Normalizer**: Módulo utilitário responsável por normalizar valores brutos (modelId, triggerType, etc.) em slugs determinísticos e compatíveis com chaves do DynamoDB antes de compor sort keys
- **Correlation_ID**: Identificador único propagado ao longo de toda a execução do pipeline ETL (tipicamente o execution ARN do Step Functions) para correlacionar logs entre a ETL_StateMachine e as invocações da Task_Lambda
- **Repository_Layer**: Camada de abstração no Backend_API que encapsula todos os padrões de acesso ao DynamoDB, isolando a lógica de negócio dos detalhes de implementação do banco de dados

## Requisitos

### Requisito 1: Schema DynamoDB Single-Table Design

**User Story:** Como desenvolvedor backend, eu quero um schema DynamoDB Single-Table Design bem definido, para que todas as consultas do dashboard sejam atendidas com latência de milissegundos a partir de uma única tabela.

#### Critérios de Aceitação

1. A Analytics_Table DEVE armazenar itens de metadados de prompts com PK `USER#{userId}` e SK `PROMPT#{timestamp}#{requestId}`
2. A Analytics_Table DEVE armazenar itens de estatísticas diárias pré-agregadas com PK `USER#{userId}` e SK `STATS#DAILY#{date}` contendo os campos: totalCredits, overageCredits, totalMessages, totalConversations, totalInteractions
3. A Analytics_Table DEVE armazenar itens de contadores de distribuição por modelo com PK `USER#{userId}` e SK `STATS#MODEL#{normalizedModelId}` contendo um campo count e um campo rawModelId com o valor original
4. A Analytics_Table DEVE armazenar itens de contadores de distribuição por trigger com PK `USER#{userId}` e SK `STATS#TRIGGER#{normalizedTriggerType}` contendo um campo count e um campo rawTriggerType com o valor original
5. A Analytics_Table DEVE armazenar itens de agregados diários globais com PK `GLOBAL` e SK `STATS#DAILY#{date}` contendo os campos: totalCredits, overageCredits, totalMessages, totalConversations, totalUsers
6. A Analytics_Table DEVE usar modo de cobrança sob demanda (PAY_PER_REQUEST)
7. A Analytics_Table DEVE ser definida no template SAM (template.yaml) como um recurso `AWS::DynamoDB::Table`

### Requisito 2: Normalização de Valores para Chaves de Sort Key (SK)

**User Story:** Como engenheiro de plataforma, eu quero regras de normalização bem definidas para valores usados como componentes de sort keys no DynamoDB, para que as chaves sejam previsíveis, consultáveis e determinísticas independentemente da variação dos dados de entrada.

#### Critérios de Aceitação

1. O SK_Normalizer DEVE aplicar uma estratégia de normalização/canonicalização para todos os valores usados como componentes de SK na Analytics_Table (modelId, triggerType e quaisquer outros campos dinâmicos futuros)
2. O SK_Normalizer DEVE aplicar as seguintes transformações em sequência: converter para lowercase, remover espaços em branco nas extremidades (trim), substituir espaços e caracteres especiais por hífens, remover caracteres não alfanuméricos exceto hífens, colapsar hífens consecutivos em um único hífen, e truncar o resultado para no máximo 128 caracteres
3. A função de normalização DEVE ser determinística: a mesma entrada DEVE sempre produzir a mesma saída normalizada (ex: "claude-opus-2.6M bla bla bla" DEVE sempre produzir o mesmo slug)
4. QUANDO a Task_Lambda normalizar um valor para uso em SK, A Task_Lambda DEVE preservar o valor original bruto nos atributos do item na Analytics_Table (ex: campo `rawModelId` junto ao `modelId` normalizado na SK)
5. O SK_Normalizer DEVE suportar um dicionário de mapeamentos canônicos configurável (ex: via variável de ambiente ou arquivo de configuração JSON) que permite mapear valores brutos conhecidos para nomes canônicos antes de aplicar a slug-ificação, permitindo adicionar novos mapeamentos sem alterar o código-fonte
6. A função de normalização DEVE produzir valores compatíveis com chaves do DynamoDB: somente caracteres lowercase alfanuméricos e hífens, sem hífens no início ou final, com comprimento máximo de 128 caracteres
7. O SK_Normalizer DEVE ser implementado como um módulo Python independente e reutilizável, importável tanto pela Task_Lambda quanto pelo Backend_API para garantir consistência na composição e consulta de chaves
8. O Backend_API DEVE usar o mesmo SK_Normalizer ao construir condições de consulta para sort keys que envolvam modelId ou triggerType, garantindo que as consultas correspondam exatamente às chaves escritas pela Task_Lambda

### Requisito 3: State Machine Step Functions para Orquestração ETL

**User Story:** Como engenheiro de plataforma, eu quero uma State Machine do Step Functions que orquestre o pipeline ETL, para que o processamento de arquivos seja paralelo, com controle de concorrência e isolamento de falhas por arquivo.

#### Critérios de Aceitação

1. QUANDO a ETL_StateMachine for iniciada (por agendamento EventBridge ou trigger manual via API), A ETL_StateMachine DEVE listar todos os arquivos S3 sob o prefixo de origem configurado e o prefixo de prompts
2. QUANDO arquivos novos não processados forem identificados, A ETL_StateMachine DEVE consultar a Processed_Files_Table para determinar quais arquivos já foram processados
3. A ETL_StateMachine DEVE usar um estado Map para processar os arquivos novos em paralelo, com limite de concorrência configurável
4. QUANDO o estado Map processar cada arquivo, A ETL_StateMachine DEVE invocar a Task_Lambda passando o bucket S3, a chave do arquivo, o tipo de arquivo (csv ou prompt) e o Correlation_ID (execution ARN do Step Functions)
5. SE a Task_Lambda falhar ao processar um arquivo individual, ENTÃO A ETL_StateMachine DEVE capturar o erro via Catch no estado Map e continuar processando os demais arquivos sem falhar a execução inteira
6. QUANDO todos os arquivos forem processados (com sucesso ou falha), A ETL_StateMachine DEVE registrar o status da execução ETL no Parameter Store do SSM contendo: timestamp, status, quantidade de arquivos processados, quantidade de registros escritos e lista de erros
7. A ETL_StateMachine DEVE ser acionável por uma regra EventBridge com agendamento configurável (cron ou rate)
8. A ETL_StateMachine DEVE ser acionável manualmente via endpoint POST /api/etl/trigger do Backend_API
9. O estado Map da ETL_StateMachine DEVE processar os arquivos em paralelo (não sequencialmente), permitindo que múltiplas instâncias da Task_Lambda executem simultaneamente até o limite de concorrência configurado

### Requisito 4: Task Lambda para Processamento de Arquivos

**User Story:** Como engenheiro de plataforma, eu quero uma Lambda de tarefa que processe um arquivo por vez como etapa do Step Functions, para que o uso de memória seja limitado e falhas sejam isoladas por arquivo.

#### Critérios de Aceitação

1. QUANDO a Task_Lambda receber um evento do Step Functions para um arquivo CSV de atividade, A Task_Lambda DEVE fazer o parse do CSV, normalizar os registros e escrever os dados de atividade na Analytics_Table
2. QUANDO a Task_Lambda receber um evento do Step Functions para um arquivo .json.gz de prompts, A Task_Lambda DEVE descompactar, fazer o parse, normalizar e escrever metadados de prompts e estatísticas na Analytics_Table
3. QUANDO escrever estatísticas diárias de um usuário, A Task_Lambda DEVE usar operações Atomic_Counter (UpdateItem com ADD) para incrementar totalCredits, overageCredits, totalMessages, totalConversations e totalInteractions no item `STATS#DAILY#{date}`
4. QUANDO escrever dados de distribuição por modelo, A Task_Lambda DEVE usar operações Atomic_Counter para incrementar o count no item `STATS#MODEL#{normalizedModelId}`
5. QUANDO escrever dados de distribuição por trigger, A Task_Lambda DEVE usar operações Atomic_Counter para incrementar o count no item `STATS#TRIGGER#{normalizedTriggerType}`
6. QUANDO escrever agregados diários globais, A Task_Lambda DEVE usar operações Atomic_Counter para incrementar os totais no item `GLOBAL` / `STATS#DAILY#{date}`
7. QUANDO o conteúdo combinado de um prompt (texto do prompt + resposta) for 4KB ou menos, A Task_Lambda DEVE armazenar o conteúdo inline no item de metadados do prompt na Analytics_Table
8. QUANDO o conteúdo combinado de um prompt exceder 4KB, A Task_Lambda DEVE armazenar o conteúdo no S3 em `prompts-content/{requestId}.json` e definir o flag `contentInS3` como true no item de metadados do prompt
9. QUANDO a Task_Lambda processar um arquivo com sucesso, A Task_Lambda DEVE marcar o arquivo como processado na Processed_Files_Table
10. SE a Task_Lambda encontrar um erro ao processar um arquivo, ENTÃO A Task_Lambda DEVE lançar uma exceção para que o Step Functions capture o erro via Catch
11. A Task_Lambda DEVE ser segura para invocação concorrente: sem estado mutável compartilhado entre invocações, sem variáveis globais mutáveis e sem dependência de ordem de execução entre arquivos diferentes
12. A Task_Lambda DEVE usar exclusivamente operações Atomic_Counter (UpdateItem com ADD) para escritas em itens de estatísticas, garantindo que invocações paralelas processando arquivos diferentes não causem condições de corrida nem perda de dados

### Requisito 5: Resolução de Nomes de Usuário nos Workers

**User Story:** Como engenheiro de plataforma, eu quero que os workers resolvam nomes de exibição dos usuários, para que registros de prompts e atividades incluam nomes legíveis.

#### Critérios de Aceitação

1. QUANDO processar um arquivo que contém IDs de usuário, A Task_Lambda DEVE resolver nomes de exibição e nomes de usuário a partir da UserNamesTable existente no DynamoDB
2. SE um ID de usuário não for encontrado na UserNamesTable, ENTÃO A Task_Lambda DEVE resolver o nome a partir do IAM Identity Center e armazenar o resultado em cache na UserNamesTable
3. QUANDO um userId de prompt contiver um prefixo de diretório (formato `d-{directoryId}.{uuid}`), A Task_Lambda DEVE extrair a porção UUID para resolução de nomes

### Requisito 6: Backend API — Listagem de Uso (Substituir Athena)

**User Story:** Como desenvolvedor frontend, eu quero que o endpoint de listagem de uso consulte o DynamoDB em vez do Athena, para que o tempo de resposta caia de segundos para milissegundos.

#### Critérios de Aceitação

1. QUANDO o Backend_API receber uma requisição GET /api/usage, O Backend_API DEVE consultar a Analytics_Table via Repository_Layer para agregar estatísticas de uso por usuário
2. QUANDO a requisição GET /api/usage incluir parâmetros startDate e endDate, O Backend_API DEVE filtrar itens de estatísticas diárias por intervalo de datas usando condições begins_with e between no SK
3. O Backend_API DEVE retornar o mesmo schema de resposta da implementação atual: summary (totalUsers, totalCredits, totalOverageCredits, averageCreditsPerUser), array users e objeto period
4. O Backend_API DEVE suportar paginação com parâmetro limit (máximo 50) e parâmetro nextToken usando o LastEvaluatedKey do DynamoDB
5. QUANDO a requisição GET /api/usage incluir um filtro subscriptionTier, O Backend_API DEVE filtrar os resultados por tier de assinatura

### Requisito 7: Backend API — Página de Detalhes do Usuário (Substituir 6 Queries Athena)

**User Story:** Como desenvolvedor frontend, eu quero que o endpoint de detalhes do usuário consulte o DynamoDB em vez de executar 6 queries sequenciais no Athena, para que a página carregue em menos de 1 segundo.

#### Critérios de Aceitação

1. QUANDO o Backend_API receber uma requisição GET /api/usage/{userId}/details, O Backend_API DEVE consultar a Analytics_Table via Repository_Layer para todos os dados usando a partition key única `USER#{userId}`
2. O Backend_API DEVE recuperar dados de uso diário consultando itens com SK começando com `STATS#DAILY#`
3. O Backend_API DEVE recuperar dados de distribuição por modelo consultando itens com SK começando com `STATS#MODEL#`
4. O Backend_API DEVE recuperar dados de distribuição por trigger consultando itens com SK começando com `STATS#TRIGGER#`
5. O Backend_API DEVE recuperar prompts recentes consultando itens com SK começando com `PROMPT#` em ordem reversa, limitado a 20 itens
6. QUANDO parâmetros startDate e endDate forem fornecidos, O Backend_API DEVE usar condições between no SK para filtrar estatísticas diárias e prompts por intervalo de datas
7. O Backend_API DEVE retornar o mesmo schema de resposta da implementação atual: userId, displayName, userName, summary, dailyUsage, modelDistribution, triggerDistribution, recentPrompts, period

### Requisito 8: Backend API — Listagem e Detalhes de Prompts

**User Story:** Como desenvolvedor frontend, eu quero que os endpoints de listagem e detalhes de prompts usem o DynamoDB, para que a navegação de prompts seja rápida e a visualização expandida carregue instantaneamente para prompts pequenos.

#### Critérios de Aceitação

1. QUANDO o Backend_API receber uma requisição GET /api/prompts, O Backend_API DEVE consultar a Analytics_Table via Repository_Layer para itens de metadados de prompts
2. QUANDO a requisição GET /api/prompts incluir um filtro userId, O Backend_API DEVE consultar a partição `USER#{userId}` com SK começando com `PROMPT#`
3. O Backend_API DEVE suportar paginação com parâmetros limit (máximo 50) e nextToken
4. QUANDO o Backend_API receber uma requisição GET /api/prompts/{requestId} e o item do prompt tiver `contentInS3` definido como true, O Backend_API DEVE buscar o conteúdo completo do S3 em `prompts-content/{requestId}.json`
5. QUANDO o Backend_API receber uma requisição GET /api/prompts/{requestId} e o item do prompt tiver conteúdo armazenado inline, O Backend_API DEVE retornar o conteúdo diretamente do item do DynamoDB
6. O Backend_API DEVE retornar os mesmos schemas de resposta da implementação atual para os endpoints de listagem e detalhes

### Requisito 9: Backend API — Uso da Conta (Substituir Athena)

**User Story:** Como desenvolvedor frontend, eu quero que o endpoint de uso da conta consulte o DynamoDB em vez do Athena, para que o dashboard da conta carregue rapidamente.

#### Critérios de Aceitação

1. QUANDO o Backend_API receber uma requisição GET /api/usage/account, O Backend_API DEVE consultar a Analytics_Table via Repository_Layer para itens de agregados globais com PK `GLOBAL` e SK começando com `STATS#DAILY#`
2. QUANDO parâmetros startDate e endDate forem fornecidos, O Backend_API DEVE filtrar itens diários globais por intervalo de datas
3. O Backend_API DEVE computar dados de timeline lendo os itens diários globais e agrupando pela granularidade solicitada (dia, semana, mês)
4. O Backend_API DEVE retornar o mesmo schema de resposta da implementação atual: totals, timeline, breakdownByTier, breakdownByClientType, period

### Requisito 10: Logs Estruturados e Observabilidade End-to-End

**User Story:** Como engenheiro de plataforma, eu quero logs estruturados e correlacionados ao longo de todo o pipeline ETL, para que eu possa diagnosticar problemas, analisar execuções end-to-end e monitorar a saúde do sistema via CloudWatch Logs Insights.

#### Critérios de Aceitação

1. A Task_Lambda e a Lambda de listagem de arquivos da ETL_StateMachine DEVEM emitir logs em formato JSON estruturado (um objeto JSON por linha de log) contendo no mínimo: timestamp, level, message e campos de contexto relevantes
2. A Task_Lambda DEVE incluir o Correlation_ID (execution ARN do Step Functions) em todas as entradas de log, permitindo filtrar todos os logs de uma execução ETL específica via CloudWatch Logs Insights
3. QUANDO a Task_Lambda iniciar o processamento de um arquivo, A Task_Lambda DEVE emitir um log com: Correlation_ID, chave S3 do arquivo, tipo de arquivo (csv ou prompt) e tamanho do arquivo em bytes
4. QUANDO a Task_Lambda concluir o processamento de um arquivo com sucesso, A Task_Lambda DEVE emitir um log com: Correlation_ID, chave S3 do arquivo, quantidade de registros processados, quantidade de itens escritos na Analytics_Table e duração do processamento em milissegundos
5. SE a Task_Lambda encontrar um erro ao processar um arquivo, ENTÃO A Task_Lambda DEVE emitir um log de erro com: Correlation_ID, chave S3 do arquivo, tipo de erro, mensagem de erro completa e stack trace
6. QUANDO a ETL_StateMachine concluir uma execução (estado final de registro de status), A ETL_StateMachine DEVE registrar um sumário da execução contendo: total de arquivos descobertos, total de arquivos novos, total processados com sucesso, total com falha, total de registros escritos, duração total da execução e lista de arquivos com erro
7. Os logs estruturados DEVEM usar nomes de campos consistentes e compatíveis com consultas do CloudWatch Logs Insights (ex: campos como `correlationId`, `s3Key`, `fileType`, `recordCount`, `durationMs`, `errorType`)
8. O Backend_API DEVE emitir logs estruturados em formato JSON para todas as requisições, incluindo: endpoint chamado, duração da consulta ao DynamoDB em milissegundos e contagem de itens retornados

### Requisito 11: Reorganização da Estrutura do Código Backend

**User Story:** Como desenvolvedor backend, eu quero o código do backend reorganizado em uma estrutura modular com separação clara de responsabilidades, para que o código seja mais manutenível, testável e fácil de navegar.

#### Critérios de Aceitação

1. O Backend_API DEVE organizar o código em módulos separados por responsabilidade: handlers (recebem eventos e delegam), repository (encapsula acesso ao DynamoDB), models (dataclasses e tipos) e utils (funções utilitárias compartilhadas como o SK_Normalizer)
2. O Backend_API DEVE implementar uma Repository_Layer que encapsule todos os padrões de acesso à Analytics_Table, expondo métodos de alto nível como `get_user_stats(userId, startDate, endDate)`, `get_user_prompts(userId, limit)`, `get_global_stats(startDate, endDate)` em vez de expor detalhes de PK/SK diretamente nos handlers
3. Os handlers do Backend_API DEVEM conter apenas lógica de roteamento HTTP, validação de parâmetros de entrada e formatação de resposta, delegando toda lógica de acesso a dados para a Repository_Layer
4. A Repository_Layer DEVE receber o cliente DynamoDB como parâmetro (injeção de dependência), permitindo substituição por mocks em testes unitários sem necessidade de patching
5. A Task_Lambda DEVE organizar o código em módulos separados: handler (entry point), processors (lógica de parse e normalização por tipo de arquivo), repository (escritas na Analytics_Table) e utils (funções compartilhadas)
6. O módulo de repository da Task_Lambda DEVE encapsular todas as operações de escrita na Analytics_Table (PutItem para prompts, UpdateItem com ADD para contadores), isolando a lógica de composição de PK/SK dos processadores de arquivo

### Requisito 12: Alterações de Infraestrutura no Template SAM

**User Story:** Como engenheiro de plataforma, eu quero o template SAM atualizado para definir a nova tabela DynamoDB, a State Machine do Step Functions e as funções Lambda, para que a infraestrutura seja implantada como código.

#### Critérios de Aceitação

1. O template SAM DEVE definir a Analytics_Table como um recurso `AWS::DynamoDB::Table` com schema de chaves PK (String) e SK (String) e cobrança PAY_PER_REQUEST
2. O template SAM DEVE definir a ETL_StateMachine como um recurso `AWS::Serverless::StateMachine` com definição da state machine em ASL (Amazon States Language)
3. O template SAM DEVE definir uma regra EventBridge (ScheduleV2) como evento da ETL_StateMachine para execução agendada
4. O template SAM DEVE definir a Task_Lambda como um recurso `AWS::Serverless::Function` sem evento de trigger (invocada diretamente pelo Step Functions)
5. O template SAM DEVE conceder à ETL_StateMachine permissão para invocar a Task_Lambda
6. O template SAM DEVE remover as definições do Athena WorkGroup, Glue Database, Glue Tables, permissões Lake Formation e custom resource de setup do Lake Formation
7. O template SAM DEVE remover variáveis de ambiente e políticas IAM relacionadas ao Athena da função Backend_API
8. O template SAM DEVE conceder à Task_Lambda acesso de leitura ao bucket S3 de origem e acesso de leitura/escrita à Analytics_Table, Processed_Files_Table, UserNamesTable e ao bucket S3 de dados
9. O template SAM DEVE conceder ao Backend_API acesso de leitura à Analytics_Table e ao bucket S3 de dados

### Requisito 13: Compatibilidade com o Frontend

**User Story:** Como desenvolvedor frontend, eu quero que o frontend continue funcionando sem alterações após a migração, para que a experiência do usuário seja preservada.

#### Critérios de Aceitação

1. O Backend_API DEVE manter todos os caminhos de endpoints existentes: GET /api/usage, GET /api/usage/account, GET /api/usage/{userId}/details, GET /api/prompts, GET /api/prompts/{requestId}
2. O Backend_API DEVE retornar payloads de resposta que estejam em conformidade com as interfaces TypeScript existentes definidas em `frontend/src/types/index.ts` (UsageResponse, AccountUsageResponse, UserDetailResponse, PromptsListResponse, PromptDetail)
3. O Backend_API DEVE preservar o formato de resposta de erro existente com campos `error` e `message`
4. O Backend_API DEVE preservar as mensagens de erro existentes em português (ex: "Nenhum dado encontrado para o userId")

### Requisito 14: Remoção de Dependências Athena/Glue

**User Story:** Como engenheiro de plataforma, eu quero todas as dependências de Athena, Glue, Lake Formation e Parquet removidas do código-fonte, para que o sistema não tenha custos de infraestrutura não utilizada nem código morto.

#### Critérios de Aceitação

1. O código-fonte do Backend_API DEVE remover o módulo `athena_client.py` e todas as importações de funções relacionadas ao Athena
2. O código-fonte do Backend_API DEVE remover a lógica de construção de queries SQL do Athena de `usage_handler.py`, `prompts_handler.py`, `user_details_handler.py` e `account_usage_handler.py`
3. O código-fonte do ETL DEVE remover o módulo `parquet_writer.py` e todas as dependências de PyArrow/Parquet
4. O código-fonte do ETL DEVE remover as funções de escrita Parquet do módulo `prompt_writer.py` (write_prompt_metadata_parquet) e a lógica de registro de partições no Glue
5. O `etl/requirements.txt` DEVE remover pyarrow de suas dependências
