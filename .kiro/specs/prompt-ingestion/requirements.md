# Documento de Requisitos — Ingestão de Prompts e Correlação com Atividade

## Introdução

O Kiro Cost Analyzer já oferece visibilidade sobre o consumo de créditos e mensagens por usuário, processando relatórios CSV de atividade via pipeline ETL e exibindo dados agregados em um dashboard web. Porém, administradores não conseguem entender **o que** os usuários estão fazendo com esses créditos — quais prompts estão enviando, quais modelos estão usando e qual é o custo por interação.

O bucket S3 de origem contém, além dos CSVs de atividade no prefixo `activities/`, logs de prompt/resposta no prefixo `prompts/` em formato JSON comprimido (`.json.gz`). Cada arquivo representa uma interação individual com o assistente, contendo o prompt do usuário, a resposta gerada, o modelo utilizado, o tipo de trigger e metadados temporais.

Esta feature visa ingerir esses logs de prompt, correlacioná-los com os dados de atividade existentes via Athena, e expor métricas de correlação (custo por interação, distribuição de modelos, distribuição de triggers) em uma nova página de detalhes do usuário no dashboard. Todas as agregações são computadas dinamicamente via Athena SQL — sem métricas pré-computadas.

## Glossário

- **Dashboard**: Interface web principal da aplicação, construída com AWS Cloudscape, que exibe relatórios de custo e permite gestão de usuários e parâmetros
- **API_Backend**: API de backend que serve dados processados para o Dashboard e gerencia operações de configuração e usuários
- **Componente_ETL**: Pipeline que extrai arquivos do bucket S3 periodicamente, faz parsing, normaliza e armazena os dados no Datastore
- **ETL_Prompts**: Extensão ou módulo do Componente_ETL responsável por processar arquivos `.json.gz` de prompts do prefixo `prompts/`
- **Datastore**: Camada de armazenamento e consulta analítica composta por S3 (Parquet), Glue Data Catalog e Athena
- **Bucket_Dados**: Bucket S3 dedicado ao armazenamento dos dados em formato Parquet
- **Bucket_Origem**: Bucket S3 onde os relatórios CSV e logs de prompts do Kiro estão armazenados
- **Athena**: Motor de consultas SQL serverless usado para executar agregações analíticas sobre os dados Parquet no S3
- **Glue_Catalog**: AWS Glue Data Catalog que mantém a definição das tabelas (schema, partições) apontando para os dados Parquet
- **Tabela_Activity**: Tabela Glue existente (`kiro_usage.activity`) com dados de consumo por usuário
- **Tabela_Prompts**: Nova tabela Glue (`kiro_usage.prompts`) com dados de prompts/respostas normalizados
- **Log_Prompt**: Arquivo `.json.gz` no prefixo `prompts/` contendo um ou mais registros de interação prompt/resposta
- **Registro_Prompt**: Estrutura normalizada de um prompt/resposta individual, extraída de um Log_Prompt
- **UserId_Prompt**: Identificador do usuário no formato `d-{directoryId}.{uuid}` presente nos logs de prompt
- **UserId_Activity**: Identificador do usuário no formato UUID presente nos dados de atividade (campo `userId`)
- **Extração_UUID**: Processo de extrair a parte UUID do UserId_Prompt (após o ponto) para correlacionar com UserId_Activity
- **Parameter_Store**: AWS Systems Manager Parameter Store, usado para persistir configurações da aplicação
- **Prefixo_Prompts**: Caminho configurável no Parameter Store que aponta para o prefixo base dos logs de prompt no Bucket_Origem
- **Cognito_UserPool**: Pool de usuários do Amazon Cognito que gerencia autenticação e autorização da aplicação
- **Template_SAM**: Template AWS SAM que define toda a infraestrutura da aplicação como código
- **Correlação**: JOIN entre Tabela_Activity e Tabela_Prompts via userId e data para calcular métricas combinadas
- **Custo_Por_Interação**: Métrica calculada como créditos consumidos dividido pelo número de interações (prompts) no mesmo período
- **Página_Detalhes_Usuário**: Nova página do Dashboard acessível ao clicar no userId na tabela principal, exibindo métricas detalhadas de consumo e prompts

## Requisitos

### Requisito 1: Pipeline ETL para ingestão de logs de prompt

**User Story:** Como administrador, eu quero que o pipeline ETL processe automaticamente os logs de prompt/resposta do bucket S3, para que os dados de interação estejam disponíveis para análise e correlação com dados de consumo.

#### Critérios de Aceitação

1. WHEN o ETL_Prompts executa, THE ETL_Prompts SHALL listar todos os arquivos `.json.gz` no Bucket_Origem sob o Prefixo_Prompts configurado, navegando a estrutura `GenerateAssistantResponse/{region}/{year}/{month}/{day}/{hour}/`
2. WHEN o ETL_Prompts encontra um arquivo `.json.gz` novo, THE ETL_Prompts SHALL descomprimir o conteúdo gzip e fazer parsing do JSON contido
3. WHEN o ETL_Prompts faz parsing de um Log_Prompt válido, THE ETL_Prompts SHALL extrair cada registro do array `records` e normalizar para a estrutura plana do Registro_Prompt
4. WHEN o ETL_Prompts normaliza um Registro_Prompt, THE ETL_Prompts SHALL extrair a parte UUID do UserId_Prompt (tudo após o caractere `.`) para armazenar como campo `userId` compatível com a Tabela_Activity
5. WHEN o ETL_Prompts processa registros normalizados, THE ETL_Prompts SHALL gravar os dados em formato Parquet no Bucket_Dados sob o caminho `prompts/year=YYYY/month=MM/`
6. THE ETL_Prompts SHALL registrar cada arquivo processado na tabela de controle do DynamoDB para evitar reprocessamento
7. IF um arquivo `.json.gz` contém JSON inválido ou estrutura inesperada, THEN THE ETL_Prompts SHALL registrar um log de erro descritivo e continuar processando os demais arquivos
8. IF o campo `records` do Log_Prompt está vazio, THEN THE ETL_Prompts SHALL ignorar o arquivo sem gerar erro
9. WHEN o ETL_Prompts conclui a execução, THE ETL_Prompts SHALL atualizar o status da execução no Parameter_Store com contadores de arquivos processados, registros gravados e erros

### Requisito 2: Configuração do prefixo de prompts

**User Story:** Como administrador, eu quero configurar o prefixo S3 dos logs de prompt via Parameter Store, para que a aplicação saiba de onde extrair os dados de prompt sem hardcode de accountId ou região.

#### Critérios de Aceitação

1. THE Template_SAM SHALL criar um parâmetro no Parameter_Store para o Prefixo_Prompts com valor padrão vazio
2. THE Template_SAM SHALL aceitar um parâmetro de deploy `PromptsPrefix` para configurar o Prefixo_Prompts inicial (ex: `prompts/AWSLogs/673826570926/KiroLogs/`)
3. WHEN o ETL_Prompts inicia uma execução, THE ETL_Prompts SHALL ler o Prefixo_Prompts a partir do Parameter_Store
4. WHEN o Prefixo_Prompts está vazio ou não configurado, THE ETL_Prompts SHALL ignorar o processamento de prompts e registrar um log informativo
5. THE Dashboard SHALL exibir o Prefixo_Prompts na tela de configuração, permitindo ao administrador visualizar e alterar o valor

### Requisito 3: Armazenamento em duas camadas — metadados (Parquet/Athena) e conteúdo (S3)

**User Story:** Como administrador, eu quero que os metadados dos prompts sejam armazenados em Parquet para queries analíticas eficientes, e o conteúdo completo dos prompts/respostas seja armazenado separadamente no S3 para acesso sob demanda, para que as consultas Athena sejam rápidas e baratas mesmo com prompts grandes.

#### Critérios de Aceitação

1. THE Template_SAM SHALL criar a Tabela_Prompts no Glue_Catalog com database `kiro_usage` e nome `prompts`
2. THE Tabela_Prompts SHALL definir apenas colunas de metadados (sem conteúdo de prompt/resposta): `userId` (string), `originalUserId` (string), `displayName` (string), `userName` (string), `timestamp` (string), `date` (string), `hour` (string), `modelId` (string), `triggerType` (string), `customizationArn` (string), `requestId` (string), `conversationId` (string), `utteranceId` (string), `region` (string), `accountId` (string), `promptLength` (bigint), `responseLength` (bigint)
3. THE Tabela_Prompts SHALL ser particionada por `year` (string) e `month` (string), seguindo o mesmo padrão da Tabela_Activity
4. THE Tabela_Prompts SHALL apontar para o caminho `s3://{DataBucket}/prompts-metadata/` como location dos dados Parquet
5. WHEN o ETL_Prompts processa um Registro_Prompt, THE ETL_Prompts SHALL gravar o conteúdo completo (prompt + resposta + metadados) como JSON individual no S3 em `s3://{DataBucket}/prompts-content/{requestId}.json`
6. THE Template_SAM SHALL configurar permissões Lake Formation para que o ETL_Prompts e o API_Backend possam acessar a Tabela_Prompts
7. WHEN o API_Backend precisa retornar o conteúdo de um prompt específico, THE API_Backend SHALL ler o arquivo JSON diretamente do S3 via `GetObject` em vez de consultar Athena

### Requisito 4: Normalização e schema do Registro_Prompt

**User Story:** Como administrador, eu quero que cada log de prompt seja normalizado para uma estrutura plana e consistente, para que os metadados sejam consultáveis via SQL e o conteúdo acessível via S3.

#### Critérios de Aceitação

1. THE ETL_Prompts SHALL extrair os metadados do campo `generateAssistantResponseEventRequest`: `modelId`, `chatTriggerType` (→ `triggerType`), `timeStamp` (→ `timestamp`), `customizationArn`
2. THE ETL_Prompts SHALL derivar `date` (YYYY-MM-DD) e `hour` (HH) a partir do campo `timeStamp`
3. THE ETL_Prompts SHALL extrair os metadados do campo `generateAssistantResponseEventResponse`: `requestId`, `conversationId`, `utteranceId`
4. THE ETL_Prompts SHALL calcular `promptLength` como o número de caracteres do campo `prompt` e `responseLength` como o número de caracteres do campo `response`
5. WHEN o campo `customizationArn` é `null`, THE ETL_Prompts SHALL armazenar string vazia
6. WHEN o campo `conversationId` é `null`, THE ETL_Prompts SHALL armazenar string vazia
7. THE ETL_Prompts SHALL gravar o conteúdo completo (prompt text + response text + todos os metadados) no arquivo JSON individual no S3 para acesso sob demanda

### Requisito 5: Extração de UUID do userId de prompts

**User Story:** Como administrador, eu quero que o userId dos logs de prompt seja normalizado para o formato UUID usado nos dados de atividade, para que a correlação entre prompts e consumo funcione corretamente.

#### Critérios de Aceitação

1. WHEN o ETL_Prompts processa um UserId_Prompt no formato `d-{directoryId}.{uuid}`, THE ETL_Prompts SHALL extrair apenas a parte `{uuid}` (tudo após o caractere `.`) e armazenar como campo `userId`
2. WHEN o ETL_Prompts processa um UserId_Prompt que não contém o caractere `.`, THE ETL_Prompts SHALL armazenar o valor original como campo `userId`
3. THE ETL_Prompts SHALL armazenar o UserId_Prompt original completo em um campo `originalUserId` para rastreabilidade
4. PARA TODOS os registros de prompt processados, a Extração_UUID SHALL produzir um `userId` que corresponda ao formato UUID usado na Tabela_Activity (propriedade de compatibilidade)

### Requisito 6: Endpoints de API para consulta de prompts

**User Story:** Como administrador, eu quero consultar os dados de prompts via API, para que o dashboard possa exibir listas de prompts com filtros e detalhes individuais.

#### Critérios de Aceitação

1. WHEN uma requisição GET é feita para `/api/prompts`, THE API_Backend SHALL executar uma consulta Athena na Tabela_Prompts e retornar uma lista paginada de prompts
2. THE API_Backend SHALL aceitar os seguintes query parameters no endpoint `/api/prompts`: `userId`, `startDate`, `endDate`, `modelId`, `triggerType`, `limit` e `nextToken`
3. WHEN o parâmetro `userId` é fornecido, THE API_Backend SHALL filtrar os resultados para incluir apenas prompts do usuário especificado
4. WHEN os parâmetros `startDate` e `endDate` são fornecidos, THE API_Backend SHALL filtrar os resultados para incluir apenas prompts cujo campo `date` esteja dentro do intervalo especificado (inclusivo)
5. WHEN uma requisição GET é feita para `/api/prompts/{requestId}`, THE API_Backend SHALL ler o conteúdo completo do prompt/resposta diretamente do S3 (`s3://{DataBucket}/prompts-content/{requestId}.json`) via `GetObject`, sem consultar Athena
6. IF o `requestId` fornecido não corresponde a nenhum registro, THEN THE API_Backend SHALL retornar status 404 com mensagem descritiva
7. THE API_Backend SHALL retornar no máximo 50 registros por página no endpoint `/api/prompts`, com suporte a paginação via `nextToken`

### Requisito 7: Endpoint de detalhes do usuário com correlação

**User Story:** Como administrador, eu quero acessar um endpoint que retorne dados detalhados de um usuário combinando consumo de atividade e prompts, para que o dashboard possa exibir métricas de correlação como custo por interação e distribuição de modelos.

#### Critérios de Aceitação

1. WHEN uma requisição GET é feita para `/api/usage/{userId}/details`, THE API_Backend SHALL executar consultas Athena que fazem JOIN entre Tabela_Activity e Tabela_Prompts usando `userId` e `date`
2. THE API_Backend SHALL retornar o consumo diário do usuário (créditos, mensagens) a partir da Tabela_Activity para o período solicitado
3. THE API_Backend SHALL retornar a contagem de interações (prompts) por dia a partir da Tabela_Prompts para o período solicitado
4. THE API_Backend SHALL calcular o Custo_Por_Interação como `SUM(creditsUsed) / COUNT(prompts)` para cada dia do período, retornando `null` quando não houver prompts no dia
5. THE API_Backend SHALL retornar a distribuição de uso por modelo (`modelId`) com contagem e percentual para o período solicitado
6. THE API_Backend SHALL retornar a distribuição de uso por tipo de trigger (`triggerType`) com contagem e percentual para o período solicitado
7. THE API_Backend SHALL retornar a lista dos prompts mais recentes do usuário (últimos 20) com campos resumidos: `timestamp`, `modelId`, `triggerType`, `promptLength`, `responseLength`, `requestId`
8. WHEN os parâmetros `startDate` e `endDate` são fornecidos, THE API_Backend SHALL filtrar todas as métricas para o período especificado
9. IF o `userId` fornecido não possui dados na Tabela_Activity nem na Tabela_Prompts, THEN THE API_Backend SHALL retornar status 404 com mensagem descritiva

### Requisito 8: Página de detalhes do usuário no Dashboard

**User Story:** Como administrador, eu quero clicar no userId na tabela do dashboard e ver uma página de detalhes com consumo diário, métricas de interação e prompts recentes, para que eu possa entender o comportamento dos usuários mais caros.

#### Critérios de Aceitação

1. WHEN o administrador clica no userId na tabela principal do Dashboard, THE Dashboard SHALL navegar para a Página_Detalhes_Usuário com o userId como parâmetro de rota
2. THE Página_Detalhes_Usuário SHALL exibir cards de resumo com: total de créditos, total de interações, custo médio por interação e total de mensagens para o período selecionado
3. THE Página_Detalhes_Usuário SHALL exibir um gráfico de linha com duas séries: consumo diário de créditos (eixo esquerdo) e contagem de interações por dia (eixo direito)
4. THE Página_Detalhes_Usuário SHALL exibir um gráfico de pizza mostrando a distribuição de uso por modelo (`modelId`)
5. THE Página_Detalhes_Usuário SHALL exibir um gráfico de pizza mostrando a distribuição de uso por tipo de trigger (`triggerType`)
6. THE Página_Detalhes_Usuário SHALL exibir uma tabela de prompts recentes com colunas: data/hora, modelo, tipo de trigger, tamanho do prompt, tamanho da resposta
7. WHEN o administrador clica em uma linha da tabela de prompts, THE Dashboard SHALL expandir a linha para exibir o conteúdo completo do prompt e da resposta
8. THE Página_Detalhes_Usuário SHALL permitir ao administrador selecionar um período (data inicial e data final) para filtrar todas as métricas exibidas
9. THE Página_Detalhes_Usuário SHALL exibir um botão de voltar que retorna à tabela principal do Dashboard

### Requisito 9: Correlação dinâmica via Athena SQL

**User Story:** Como administrador, eu quero que todas as métricas de correlação sejam calculadas dinamicamente via Athena SQL, para que os dados estejam sempre atualizados sem necessidade de pipelines de pré-computação.

#### Critérios de Aceitação

1. THE API_Backend SHALL executar JOINs entre Tabela_Activity e Tabela_Prompts usando as colunas `userId` e `date` como chaves de correlação
2. THE API_Backend SHALL usar LEFT JOIN da Tabela_Activity para a Tabela_Prompts, garantindo que usuários sem prompts ainda apareçam nos resultados com contagem de interações zero
3. THE API_Backend SHALL utilizar filtros de partição (`year` e `month`) nas consultas Athena para otimizar o scan de dados
4. THE API_Backend SHALL calcular métricas de tamanho médio de prompt (`AVG(promptLength)`) e tamanho médio de resposta (`AVG(responseLength)`) por usuário via Athena SQL
5. IF a Tabela_Prompts não contém dados para o período solicitado, THEN THE API_Backend SHALL retornar as métricas de atividade normalmente com campos de correlação zerados

### Requisito 10: Infraestrutura SAM para a feature de prompts

**User Story:** Como administrador, eu quero que toda a infraestrutura necessária para a ingestão de prompts seja definida no Template SAM existente, para que o deploy seja unificado e reprodutível.

#### Critérios de Aceitação

1. THE Template_SAM SHALL definir a Tabela_Prompts no Glue_Catalog com schema e partições conforme o Requisito 3
2. THE Template_SAM SHALL definir o parâmetro `PromptsPrefix` com valor padrão vazio e criar o parâmetro correspondente no Parameter_Store
3. THE Template_SAM SHALL configurar permissões IAM para que o ETL_Prompts possa ler arquivos `.json.gz` do Bucket_Origem sob o prefixo `prompts/`
4. THE Template_SAM SHALL configurar permissões IAM para que o ETL_Prompts possa gravar Parquet no Bucket_Dados sob o caminho `prompts/`
5. THE Template_SAM SHALL configurar permissões Lake Formation para que o ETL_Prompts e o API_Backend possam acessar a Tabela_Prompts
6. THE Template_SAM SHALL adicionar os novos endpoints de API (`/api/prompts`, `/api/prompts/{requestId}`, `/api/usage/{userId}/details`) ao API Gateway com autenticação Cognito
7. THE Template_SAM SHALL configurar variáveis de ambiente no BackendFunction e EtlFunction para referenciar a Tabela_Prompts e o Prefixo_Prompts

### Requisito 11: Parsing e serialização de logs de prompt (round-trip)

**User Story:** Como administrador, eu quero que o parsing dos logs `.json.gz` de prompt seja robusto e verificável, para que nenhuma informação seja perdida durante a ingestão.

#### Critérios de Aceitação

1. THE ETL_Prompts SHALL descomprimir arquivos `.json.gz` usando decodificação gzip padrão e fazer parsing do conteúdo como JSON UTF-8
2. WHEN um arquivo `.json.gz` contém múltiplos registros no array `records`, THE ETL_Prompts SHALL processar cada registro individualmente e gerar um Registro_Prompt por entrada
3. PARA TODOS os Registro_Prompt válidos, serializar para Parquet e depois ler via Athena SHALL produzir valores equivalentes aos campos originais do JSON (propriedade round-trip)
4. IF um arquivo `.json.gz` não pode ser descomprimido, THEN THE ETL_Prompts SHALL registrar um log de erro com o nome do arquivo e a exceção, e continuar processando os demais arquivos
5. IF o conteúdo descomprimido não é JSON válido, THEN THE ETL_Prompts SHALL registrar um log de erro descritivo e continuar processando os demais arquivos

### Requisito 12: Navegação e roteamento do Dashboard

**User Story:** Como administrador, eu quero que a navegação do dashboard inclua a nova página de detalhes do usuário de forma integrada, para que a experiência de uso seja fluida e consistente.

#### Critérios de Aceitação

1. THE Dashboard SHALL registrar a rota `/user/:userId` no React Router para a Página_Detalhes_Usuário
2. WHEN o administrador clica no userId na tabela do Dashboard, THE Dashboard SHALL navegar para `/user/{userId}` usando navegação client-side (sem reload da página)
3. THE Dashboard SHALL exibir o userId como link clicável na tabela principal de consumo
4. THE Página_Detalhes_Usuário SHALL exibir o userId no cabeçalho da página para identificação clara
5. WHEN o administrador acessa diretamente a URL `/user/{userId}`, THE Dashboard SHALL carregar a Página_Detalhes_Usuário com os dados do usuário especificado

### Requisito 13: Resolução de nomes de usuário via IAM Identity Center

**User Story:** Como administrador, eu quero ver o nome real dos usuários (ex: "Vinicius Batista") em vez de UUIDs no dashboard, para que eu possa identificar rapidamente quem está consumindo mais créditos.

#### Critérios de Aceitação

1. THE Template_SAM SHALL aceitar um parâmetro de deploy `IdentityStoreId` com valor padrão vazio, representando o Identity Store ID do IAM Identity Center (ex: `d-94671e1709`)
2. THE Template_SAM SHALL criar um parâmetro no Parameter_Store (`/kiro-cost-analyzer/identity-store-id`) com o valor do `IdentityStoreId`
3. WHEN o IdentityStoreId está configurado e o ETL processa registros de atividade, THE ETL SHALL coletar todos os userIds únicos e resolver seus nomes via API `identitystore:DescribeUser`
4. THE ETL SHALL armazenar o mapeamento `userId → displayName, userName (email)` em uma tabela DynamoDB de cache (`UserNamesTable`) com campos: `userId` (PK), `displayName`, `userName`, `resolvedAt` (timestamp ISO 8601)
5. WHEN o ETL resolve um userId que já existe na UserNamesTable com `resolvedAt` nos últimos 7 dias, THE ETL SHALL reutilizar o valor cacheado sem chamar a API do Identity Center
6. WHEN o IdentityStoreId está vazio ou não configurado, THE ETL SHALL ignorar a resolução de nomes e o dashboard exibirá apenas os UUIDs (graceful degradation)
7. IF a chamada `identitystore:DescribeUser` falha para um userId específico (usuário não encontrado ou erro de API), THEN THE ETL SHALL registrar um log de warning e continuar processando — o dashboard exibirá o UUID para esse usuário
8. THE Template_SAM SHALL configurar permissões IAM para que o ETL possa chamar `identitystore:DescribeUser` e `identitystore:ListUsers`
9. THE Template_SAM SHALL criar a UserNamesTable (DynamoDB) com PK=userId (String) e billing PAY_PER_REQUEST
10. WHEN o ETL grava registros de atividade no Parquet, THE ETL SHALL incluir as colunas `displayName` e `userName` no schema da Tabela_Activity, preenchidas com os valores resolvidos do cache DynamoDB
11. WHEN o ETL grava registros de prompts no Parquet de metadados, THE ETL SHALL incluir as colunas `displayName` e `userName` no schema da Tabela_Prompts, preenchidas com os valores resolvidos do cache DynamoDB
12. IF o nome não foi resolvido para um userId, THEN THE ETL SHALL gravar string vazia nas colunas `displayName` e `userName` do Parquet

### Requisito 14: Exibição de nomes de usuário no Dashboard

**User Story:** Como administrador, eu quero que o dashboard exiba o nome real do usuário ao lado do UUID em todas as tabelas e páginas, para uma experiência mais amigável.

#### Critérios de Aceitação

1. WHEN o API_Backend executa queries Athena de consumo por usuário, THE API_Backend SHALL incluir `displayName` e `userName` nos campos retornados, lidos diretamente do Parquet via Athena (sem consulta adicional ao DynamoDB)
2. THE Dashboard SHALL exibir o `displayName` como coluna principal na tabela de consumo, com o `userId` (UUID) como texto secundário ou tooltip
3. THE Página_Detalhes_Usuário SHALL exibir o `displayName` no cabeçalho da página junto com o `userId`
4. WHEN o `displayName` está vazio no Parquet (nome não resolvido ou Identity Center não configurado), THE Dashboard SHALL exibir apenas o UUID como fallback
5. THE Dashboard SHALL permitir ao administrador configurar o `IdentityStoreId` na tela de Configurações, com validação e feedback
