# Documento de Requisitos — Categorização Automática de Prompts

## Introdução

Esta feature adiciona categorização automática de prompts ao pipeline ETL existente, utilizando o Amazon Bedrock com o modelo Amazon Nova Micro. Cada prompt processado pelo ETL será classificado em uma das 14 categorias pré-definidas (Code Generation, Debugging, Refactoring, etc.) através de inferência cross-region (us-east-1). A categoria é persistida no DynamoDB junto aos metadados do prompt, e estatísticas de distribuição por categoria são mantidas por usuário. O frontend exibe a categoria como badge colorido na tabela de prompts recentes e um gráfico de pizza com a distribuição de categorias na página de detalhes do usuário.

## Glossário

- **Pipeline_ETL**: Pipeline de processamento de dados implementado com AWS Step Functions que lista, parseia e persiste arquivos de log do Kiro no DynamoDB.
- **WriterFunction**: Lambda do pipeline ETL responsável por persistir registros parseados no DynamoDB e S3.
- **AnalyticsWriter**: Módulo Python que encapsula todas as operações de escrita no DynamoDB (Analytics_Table).
- **AnalyticsRepository**: Módulo Python que encapsula todas as operações de leitura no DynamoDB (Analytics_Table).
- **Categorizador**: Módulo Python responsável por invocar o Amazon Bedrock para classificar o conteúdo de um prompt em uma categoria.
- **Analytics_Table**: Tabela DynamoDB single-table design com PK/SK que armazena prompts, estatísticas diárias e distribuições.
- **Armazenamento_Hibrido**: Estratégia onde prompts com conteúdo combinado > 4KB são armazenados no S3 (chave `prompts-content/{requestId}.json`) em vez de inline no DynamoDB.
- **Nova_Micro**: Modelo Amazon Nova Micro utilizado para classificação de prompts. Disponível In-Region em us-east-1 e via US Geo Cross-Region (model ID: `us.amazon.nova-micro-v1:0`) quando invocado a partir de regiões US. A Lambda em sa-east-1 utiliza o Bedrock client apontando para us-east-1 com o model ID geo cross-region `us.amazon.nova-micro-v1:0`.
- **Few_Shot_Prompt**: System prompt com exemplos concretos para cada categoria, validado em testes locais com taxa de "Other" reduzida de 67% para 6,5%.
- **UserDetailPage**: Página React do frontend que exibe detalhes de uso de um usuário específico, incluindo gráficos de distribuição e tabela de prompts recentes.
- **DistributionCharts**: Componente React que renderiza gráficos de pizza para distribuições (modelo, trigger e agora categoria).
- **RecentPromptsTable**: Componente React que renderiza a tabela de prompts recentes com colunas de metadados.
- **Categoria**: Uma das 15 classificações possíveis para um prompt: Code Generation, Debugging, Refactoring, Documentation, Testing, Code Review, Architecture/Design, DevOps/Infrastructure, Data Analysis, Production Troubleshooting, Feedback/Critique, Planning/Discussion, General Q&A, Other, Empty.

## Requisitos

### Requisito 1: Módulo Categorizador de Prompts

**User Story:** Como desenvolvedor do pipeline ETL, eu quero um módulo isolado de categorização de prompts, para que a lógica de classificação via Bedrock seja reutilizável e testável independentemente.

#### Critérios de Aceitação

1. THE Categorizador SHALL classificar o conteúdo de um prompt em exatamente uma das 14 categorias pré-definidas: Code Generation, Debugging, Refactoring, Documentation, Testing, Code Review, Architecture/Design, DevOps/Infrastructure, Data Analysis, Production Troubleshooting, Feedback/Critique, Planning/Discussion, General Q&A, Other.
2. THE Categorizador SHALL utilizar o modelo Nova_Micro via Amazon Bedrock com inferência US Geo Cross-Region, utilizando o model ID `us.amazon.nova-micro-v1:0` e o Bedrock client apontando para a região us-east-1.
3. THE Categorizador SHALL enviar um Few_Shot_Prompt como system prompt contendo exemplos concretos para cada categoria.
4. THE Categorizador SHALL truncar o conteúdo do prompt para no máximo 5000 caracteres antes de enviar ao Bedrock, para controlar custos de tokens.
5. THE Categorizador SHALL utilizar temperatura 0.0 e maxTokens 20 na configuração de inferência.
6. WHEN a resposta do Bedrock não corresponder a nenhuma das 14 categorias válidas, THEN THE Categorizador SHALL retornar "Other" como categoria.
7. IF uma exceção ocorrer durante a invocação do Bedrock, THEN THE Categorizador SHALL retornar "Other" como categoria e registrar o erro no log.
8. WHEN o conteúdo do prompt estiver vazio, THE Categorizador SHALL retornar "Empty" como categoria sem invocar o Bedrock.

### Requisito 2: Integração da Categorização no Pipeline ETL

**User Story:** Como operador do sistema, eu quero que cada prompt processado pelo ETL seja automaticamente categorizado, para que a categoria esteja disponível para consulta e análise.

#### Critérios de Aceitação

1. WHEN a WriterFunction processar um registro de prompt com conteúdo não-vazio, THE WriterFunction SHALL invocar o Categorizador para obter a categoria do prompt.
2. WHEN a WriterFunction processar um registro de prompt com conteúdo vazio, THE WriterFunction SHALL atribuir a categoria "Empty" sem invocar o Categorizador.
3. THE AnalyticsWriter SHALL persistir o campo `category` no item de prompt do DynamoDB (PK: `USER#{userId}`, SK: `PROMPT#{timestamp}#{requestId}`).
4. WHEN um prompt for categorizado com sucesso, THE AnalyticsWriter SHALL incrementar o contador de distribuição de categoria do usuário (PK: `USER#{userId}`, SK: `STATS#CATEGORY#{category}`) com contagem atômica via UpdateItem ADD.
5. THE AnalyticsWriter SHALL persistir o valor bruto da categoria via `SET if_not_exists` no item de distribuição de categoria, seguindo o padrão existente de distribuição por modelo e trigger.

### Requisito 3: Leitura de Distribuição de Categorias no Backend

**User Story:** Como desenvolvedor do frontend, eu quero que a API retorne a distribuição de categorias de um usuário, para que eu possa exibir o gráfico de pizza no frontend.

#### Critérios de Aceitação

1. THE AnalyticsRepository SHALL consultar itens com SK começando por `STATS#CATEGORY#` para um dado userId, retornando a lista de categorias com contagem.
2. THE user_details_handler SHALL incluir o campo `categoryDistribution` na resposta de `GET /api/usage/{userId}/details`, contendo uma lista de objetos com `category`, `count` e `percentage`.
3. THE user_details_handler SHALL calcular a porcentagem de cada categoria em relação ao total de prompts categorizados.
4. THE prompts_handler SHALL incluir o campo `category` nos metadados de cada prompt retornado por `GET /api/prompts` e `GET /api/prompts/{requestId}`.

### Requisito 4: Exibição de Categoria na Tabela de Prompts Recentes

**User Story:** Como usuário do dashboard, eu quero ver a categoria de cada prompt na tabela de prompts recentes, para que eu possa identificar rapidamente o tipo de interação.

#### Critérios de Aceitação

1. THE RecentPromptsTable SHALL exibir uma coluna "Categoria" com um badge/tag colorido para cada prompt.
2. WHEN o campo `category` de um prompt estiver vazio ou ausente, THE RecentPromptsTable SHALL exibir um badge com o texto "N/A" em cor neutra.
3. THE RecentPromptsTable SHALL atribuir cores distintas e consistentes para cada uma das 14 categorias.

### Requisito 5: Gráfico de Distribuição por Categoria

**User Story:** Como usuário do dashboard, eu quero ver um gráfico de pizza com a distribuição de categorias dos prompts de um usuário, para que eu possa entender o perfil de uso.

#### Critérios de Aceitação

1. THE DistributionCharts SHALL renderizar um gráfico de pizza adicional com a distribuição de categorias, ao lado dos gráficos existentes de modelo e trigger.
2. THE DistributionCharts SHALL exibir o nome da categoria, a contagem e a porcentagem no popover de detalhes de cada segmento do gráfico.
3. WHEN não houver dados de distribuição de categorias, THE DistributionCharts SHALL exibir a mensagem "Nenhum dado disponível." no lugar do gráfico.
4. WHILE os dados estiverem carregando, THE DistributionCharts SHALL exibir o indicador de carregamento "Carregando..." no lugar do gráfico de categorias.

### Requisito 6: Tipos TypeScript e Interface de Dados

**User Story:** Como desenvolvedor do frontend, eu quero tipos TypeScript atualizados para suportar a categorização, para que o código seja type-safe e auto-documentado.

#### Critérios de Aceitação

1. THE frontend SHALL definir a interface `CategoryDistribution` com os campos `category` (string), `count` (number) e `percentage` (number).
2. THE frontend SHALL adicionar o campo `category` à interface `RecentPrompt`.
3. THE frontend SHALL adicionar o campo `category` à interface `PromptMetadata`.
4. THE frontend SHALL adicionar o campo `categoryDistribution` (array de `CategoryDistribution`) à interface `UserDetailResponse`.

### Requisito 7: Infraestrutura e Permissões

**User Story:** Como operador de infraestrutura, eu quero que a Lambda do ETL tenha permissão para invocar o Bedrock, para que a categorização funcione em produção.

#### Critérios de Aceitação

1. THE template SAM SHALL conceder à WriterFunction a permissão `bedrock:InvokeModel` para o modelo Nova_Micro na região us-east-1.
2. THE template SAM SHALL definir a variável de ambiente `BEDROCK_MODEL_ID` na WriterFunction com o valor `us.amazon.nova-micro-v1:0`.
3. THE template SAM SHALL definir a variável de ambiente `BEDROCK_REGION` na WriterFunction com o valor `us-east-1`.
