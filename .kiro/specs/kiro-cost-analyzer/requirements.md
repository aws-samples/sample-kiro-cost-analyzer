# Documento de Requisitos — Kiro Cost Analyzer

## Introdução

O Kiro (IDE) não oferece visibilidade nativa sobre quanto cada usuário está consumindo em créditos e mensagens. Administradores de organizações que utilizam o Kiro Enterprise precisam entender o consumo individual para otimizar custos, identificar padrões de uso e tomar decisões sobre planos de assinatura.

O Kiro exporta relatórios diários de atividade por usuário em arquivos CSV para um bucket S3. Este projeto visa criar uma aplicação web com dashboard interativo (usando AWS Cloudscape como design system) que lê esses CSVs diretamente do S3, processa e armazena os dados em formato Parquet no S3 (consultados via Athena), e exibe relatórios de custo por usuário e por conta com visualizações úteis para administradores. A aplicação é composta por dois componentes principais: um pipeline ETL para extração e processamento dos dados, e uma interface web (dashboard) com API de backend para visualização e gestão.

Toda a infraestrutura é provisionada via Infrastructure as Code usando AWS SAM, e a autenticação/autorização é gerenciada pelo Amazon Cognito.

## Glossário

- **Dashboard**: Interface web principal da aplicação, construída com AWS Cloudscape, que exibe relatórios de custo e permite gestão de usuários e parâmetros
- **API_Backend**: API de backend que serve dados processados para o Dashboard e gerencia operações de configuração e usuários
- **Componente_ETL**: Pipeline que extrai arquivos CSV do bucket S3 periodicamente, faz parsing, normaliza e armazena os dados no Datastore
- **Datastore**: Camada de armazenamento e consulta analítica composta por S3 (dados em formato Parquet particionados por ano/mês), Glue Data Catalog (metadados da tabela) e Athena (motor de consultas SQL). DynamoDB é usado apenas para dados operacionais (arquivos processados, configurações)
- **Bucket_Dados**: Bucket S3 dedicado ao armazenamento dos dados de atividade em formato Parquet, separado do Bucket_Origem
- **Athena**: Motor de consultas SQL serverless da AWS usado para executar agregações analíticas sobre os dados Parquet no S3
- **Glue_Catalog**: AWS Glue Data Catalog que mantém a definição da tabela (schema, partições) apontando para os dados Parquet no Bucket_Dados
- **Relatório_CSV**: Arquivo CSV gerado diariamente pelo Kiro contendo métricas de atividade por usuário, salvo no S3
- **Formato_Novo**: Layout de CSV com colunas: Date, UserId, Client_Type, Subscription_Tier, ProfileId, Total_Messages, Chat_Conversations, Credits_Used, Overage_Enabled, Overage_Cap, Overage_Credits_Used
- **~~Formato_Legado~~**: *(Removido — dados legados do Q Developer não são suportados)*
- **Parser_CSV**: Componente dentro do Componente_ETL responsável por ler e interpretar os arquivos CSV em estruturas de dados internas
- **Bucket_Origem**: Bucket S3 onde os relatórios CSV do Kiro estão armazenados
- **Parameter_Store**: AWS Systems Manager Parameter Store, usado para persistir configurações da aplicação (ex: nome do Bucket_Origem)
- **Cognito_UserPool**: Pool de usuários do Amazon Cognito que gerencia autenticação e autorização da aplicação
- **Usuário_Admin**: Usuário inicial com privilégios administrativos, criado automaticamente durante o deploy da aplicação
- **Créditos**: Unidade de consumo do plano Kiro do usuário (campo Credits_Used)
- **Overage**: Créditos consumidos além do limite do plano, quando habilitado pelo administrador
- **Período**: Intervalo de datas selecionado pelo usuário para análise (um ou mais dias)
- **Tipo_Cliente**: Tipo de cliente Kiro utilizado — KIRO_IDE, KIRO_CLI ou PLUGIN
- **Template_SAM**: Template AWS SAM (Serverless Application Model) que define toda a infraestrutura da aplicação como código

## Requisitos

### Requisito 1: Infraestrutura como Código com AWS SAM

**User Story:** Como administrador, eu quero que toda a infraestrutura da aplicação seja definida como código usando AWS SAM, para que eu possa provisionar e atualizar o ambiente de forma reprodutível e automatizada.

#### Critérios de Aceitação

1. THE Template_SAM SHALL definir todos os recursos da aplicação incluindo: funções Lambda, API Gateway, tabelas do Datastore, Cognito_UserPool, roles IAM e Parameter_Store
2. WHEN o comando `sam deploy` é executado, THE Template_SAM SHALL provisionar todos os recursos necessários para a aplicação funcionar
3. THE Template_SAM SHALL aceitar parâmetros de configuração para: nome do stack, nome do Bucket_Origem inicial e email do Usuário_Admin
4. WHEN o deploy é executado pela primeira vez, THE Template_SAM SHALL criar o Usuário_Admin no Cognito_UserPool com o email fornecido como parâmetro
5. IF o deploy falhar parcialmente, THEN THE Template_SAM SHALL permitir rollback automático via CloudFormation

### Requisito 2: Autenticação e autorização com Amazon Cognito

**User Story:** Como administrador, eu quero que a aplicação tenha autenticação e autorização via Cognito, para que apenas usuários autorizados possam acessar os dados de consumo.

#### Critérios de Aceitação

1. THE Cognito_UserPool SHALL exigir autenticação de todos os usuários antes de permitir acesso ao Dashboard
2. WHEN o deploy inicial é realizado, THE Template_SAM SHALL criar o Usuário_Admin com role de administrador no Cognito_UserPool
3. WHEN o Usuário_Admin acessa a tela de gestão de usuários, THE Dashboard SHALL permitir adicionar novos usuários ao Cognito_UserPool
4. WHEN o Usuário_Admin acessa a tela de gestão de usuários, THE Dashboard SHALL permitir remover usuários existentes do Cognito_UserPool
5. WHEN um usuário não autenticado tenta acessar o Dashboard, THE Dashboard SHALL redirecionar para a tela de login do Cognito
6. THE API_Backend SHALL validar o token JWT do Cognito em todas as requisições antes de processar a operação

### Requisito 3: Configuração do Bucket S3 de origem

**User Story:** Como administrador, eu quero configurar qual bucket S3 contém os relatórios CSV do Kiro, para que a aplicação saiba de onde extrair os dados sem precisar reconfigurar a cada uso.

#### Critérios de Aceitação

1. THE Dashboard SHALL exibir uma tela de configuração onde o usuário pode selecionar ou informar o nome do Bucket_Origem
2. WHEN o usuário salva a configuração do Bucket_Origem, THE API_Backend SHALL persistir o nome do bucket no Parameter_Store
3. WHEN o Componente_ETL inicia uma execução, THE Componente_ETL SHALL ler o nome do Bucket_Origem a partir do Parameter_Store
4. WHEN o Template_SAM recebe o parâmetro de Bucket_Origem inicial, THE Template_SAM SHALL salvar o valor no Parameter_Store durante o deploy
5. IF o Bucket_Origem configurado não existe ou não está acessível, THEN THE API_Backend SHALL retornar um erro descritivo indicando o problema de acesso ao bucket

### Requisito 4: Pipeline ETL — Extração e parsing de CSVs do S3

**User Story:** Como administrador, eu quero que um pipeline ETL extraia e processe automaticamente os arquivos CSV do bucket S3, para que os dados estejam sempre atualizados no datastore sem intervenção manual.

#### Critérios de Aceitação

1. THE Componente_ETL SHALL executar periodicamente em um agendamento configurável (padrão: uma vez por dia)
2. WHEN o Componente_ETL executa, THE Componente_ETL SHALL listar todos os arquivos CSV no Bucket_Origem e identificar arquivos novos ou não processados
3. WHEN um arquivo CSV válido no Formato_Novo é encontrado no Bucket_Origem, THE Parser_CSV SHALL fazer o parsing do arquivo e retornar uma lista de registros de atividade de usuário
4. ~~REMOVIDO — Formato legado (by_user_analytic) não é mais suportado. Apenas o formato novo (user_report) é processado.~~
5. IF um arquivo CSV com formato desconhecido é encontrado, THEN THE Componente_ETL SHALL registrar um log de erro descritivo indicando as colunas esperadas e as colunas encontradas, e continuar processando os demais arquivos
6. IF um arquivo CSV está vazio ou contém apenas o cabeçalho, THEN THE Parser_CSV SHALL ignorar o arquivo sem gerar erro
7. WHEN múltiplos arquivos CSV de partes (part_1, part_2, etc.) estão no Bucket_Origem, THE Parser_CSV SHALL combinar todos os registros em uma única lista
8. WHEN o parsing é concluído com sucesso, THE Componente_ETL SHALL armazenar os registros processados no Datastore
9. THE Componente_ETL SHALL manter registro de quais arquivos já foram processados para evitar reprocessamento desnecessário

### Requisito 5: ~~Tratamento de dados do formato legado~~ [REMOVIDO]

> ⚠️ **Requisito removido.** O formato legado (`by_user_analytic/`) era do Q Developer e não contém dados relevantes para o Kiro Cost Analyzer. Apenas o formato novo (`user_report/`) é suportado.

### Requisito 6: Datastore analítico com S3/Parquet e Athena

**User Story:** Como administrador, eu quero que os dados processados sejam armazenados em formato Parquet no S3 e consultados via Athena, para que o dashboard execute agregações SQL eficientes sobre grandes volumes de dados com baixo custo.

#### Critérios de Aceitação

1. WHEN o Componente_ETL processa registros, THE Componente_ETL SHALL gravar os dados de atividade em formato Parquet no Bucket_Dados, particionado por ano e mês (year=YYYY/month=MM)
2. THE Glue_Catalog SHALL manter uma definição de tabela com o schema dos registros de atividade apontando para o Bucket_Dados
3. THE Athena SHALL suportar consultas SQL por intervalo de datas (Date entre data_inicial e data_final) de forma eficiente usando partições
4. THE Athena SHALL suportar consultas filtradas por Subscription_Tier e Tipo_Cliente via cláusulas WHERE
5. WHEN o Componente_ETL grava dados no Bucket_Dados, THE Componente_ETL SHALL particionar os arquivos Parquet por ano e mês para otimizar consultas com filtro de data
6. IF dados para o mesmo UserId, Date e Tipo_Cliente já existem no Bucket_Dados, THEN THE Componente_ETL SHALL sobrescrever a partição correspondente para evitar duplicação
7. THE DynamoDB SHALL ser utilizado exclusivamente para dados operacionais: registro de arquivos processados (ProcessedFilesTable), configurações e status do ETL

### Requisito 7: Agregação de dados de consumo por usuário

**User Story:** Como administrador, eu quero que os dados de consumo sejam agregados por usuário ao longo de um período, para que eu possa ver o total de créditos e mensagens de cada pessoa no dashboard.

#### Critérios de Aceitação

1. WHEN registros de múltiplos dias são consultados, THE API_Backend SHALL executar consultas SQL via Athena para agregar Credits_Used, Total_Messages, Chat_Conversations e Overage_Credits_Used por UserId
2. WHEN registros de múltiplos Tipo_Cliente existem para o mesmo UserId, THE API_Backend SHALL agregar os dados de todos os tipos de cliente em um único registro consolidado por usuário
3. THE API_Backend SHALL calcular o custo total por usuário como a soma de Credits_Used e Overage_Credits_Used no Período selecionado
4. THE API_Backend SHALL calcular a média diária de Credits_Used por usuário no Período selecionado
5. WHEN um filtro de período (data inicial e data final) é fornecido pelo Dashboard, THE API_Backend SHALL incluir apenas registros cujo campo Date esteja dentro do intervalo especificado (inclusivo)
6. IF nenhum filtro de período é fornecido, THEN THE API_Backend SHALL processar todos os registros disponíveis no Datastore

### Requisito 8: Visualização de consumo total da conta (account-level)

**User Story:** Como administrador, eu quero visualizar o consumo total agregado de todos os usuários da conta Kiro, para que eu possa entender o gasto global da organização, identificar tendências temporais e analisar a distribuição de consumo por tier e tipo de cliente.

#### Critérios de Aceitação

1. THE API_Backend SHALL calcular e retornar o total de Credits_Used de todos os usuários da conta no Período selecionado
2. THE API_Backend SHALL calcular e retornar o total de Overage_Credits_Used de todos os usuários da conta no Período selecionado
3. THE API_Backend SHALL calcular e retornar o total de Total_Messages de todos os usuários da conta no Período selecionado
4. THE API_Backend SHALL calcular e retornar o total de Chat_Conversations de todos os usuários da conta no Período selecionado
5. WHEN um filtro de período é fornecido, THE API_Backend SHALL retornar a evolução temporal do consumo da conta agrupada por dia, semana ou mês conforme o parâmetro de granularidade
6. THE API_Backend SHALL retornar o breakdown de consumo por Subscription_Tier, incluindo total de créditos, total de overage e total de mensagens para cada tier
7. THE API_Backend SHALL retornar o breakdown de consumo por Tipo_Cliente, incluindo total de créditos, total de overage e total de mensagens para cada tipo de cliente
8. THE Dashboard SHALL exibir os totais da conta (créditos, overage, mensagens, conversas) em cards de resumo na seção de consumo account-level
9. THE Dashboard SHALL exibir um gráfico de linha mostrando a evolução temporal do consumo da conta (por dia, semana ou mês)
10. THE Dashboard SHALL exibir gráficos de breakdown por Subscription_Tier e por Tipo_Cliente mostrando a proporção de consumo de cada segmento

### Requisito 9: Interface web — Dashboard de consumo

**User Story:** Como administrador, eu quero visualizar os dados de consumo em um dashboard web interativo, para que eu possa analisar custos de forma visual e intuitiva.

#### Critérios de Aceitação

1. THE Dashboard SHALL ser construído utilizando AWS Cloudscape como design system
2. THE Dashboard SHALL exibir uma tabela com as colunas: UserId, Subscription_Tier, Total de Créditos, Créditos de Overage, Total de Mensagens, Total de Conversas e Média Diária de Créditos
3. THE Dashboard SHALL ordenar os usuários por Total de Créditos em ordem decrescente (maior consumidor primeiro) por padrão
4. THE Dashboard SHALL permitir ao usuário selecionar um período (data inicial e data final) para filtrar os dados exibidos
5. THE Dashboard SHALL permitir filtrar os dados por Subscription_Tier (PRO, PRO_PLUS ou POWER)
6. THE Dashboard SHALL permitir filtrar os dados por Tipo_Cliente (KIRO_IDE, KIRO_CLI ou PLUGIN)
7. THE Dashboard SHALL permitir filtrar apenas usuários com Overage_Credits_Used maior que zero
8. THE Dashboard SHALL exibir um resumo geral contendo: total de usuários, soma total de créditos, soma total de créditos de overage e média de créditos por usuário
9. THE Dashboard SHALL permitir exportar os dados filtrados em formato CSV ou JSON

### Requisito 10: Interface web — Gestão de usuários

**User Story:** Como administrador, eu quero gerenciar os usuários da aplicação a partir do dashboard, para que eu possa controlar quem tem acesso aos dados de consumo.

#### Critérios de Aceitação

1. THE Dashboard SHALL exibir uma tela dedicada de gestão de usuários acessível apenas pelo Usuário_Admin
2. WHEN o Usuário_Admin acessa a tela de gestão, THE Dashboard SHALL listar todos os usuários cadastrados no Cognito_UserPool com seus status (ativo, desativado)
3. WHEN o Usuário_Admin preenche o formulário de novo usuário com email, THE API_Backend SHALL criar o usuário no Cognito_UserPool e enviar um convite por email
4. WHEN o Usuário_Admin solicita a remoção de um usuário, THE API_Backend SHALL desativar o usuário no Cognito_UserPool
5. IF o Usuário_Admin tenta remover a si mesmo, THEN THE Dashboard SHALL exibir um erro impedindo a operação

### Requisito 11: Interface web — Configuração de parâmetros

**User Story:** Como administrador, eu quero configurar os parâmetros da aplicação pelo dashboard, para que eu possa ajustar o comportamento sem precisar acessar o console AWS.

#### Critérios de Aceitação

1. THE Dashboard SHALL exibir uma tela de configuração onde o Usuário_Admin pode visualizar e alterar o Bucket_Origem
2. WHEN o Usuário_Admin altera o Bucket_Origem, THE API_Backend SHALL validar o acesso ao bucket antes de salvar a configuração no Parameter_Store
3. THE Dashboard SHALL exibir o status da última execução do Componente_ETL (data/hora, sucesso/falha, quantidade de registros processados)
4. THE Dashboard SHALL permitir ao Usuário_Admin disparar uma execução manual do Componente_ETL

### Requisito 12: Serialização e round-trip de dados

**User Story:** Como administrador, eu quero que os dados exportados do dashboard possam ser reimportados sem perda de informação, para que eu possa usar os relatórios como entrada para outras ferramentas.

#### Critérios de Aceitação

1. THE API_Backend SHALL formatar registros agregados em formato CSV válido com cabeçalho quando solicitado pelo Dashboard
2. THE API_Backend SHALL formatar registros agregados em formato JSON válido quando solicitado pelo Dashboard
3. PARA TODOS os registros agregados válidos, fazer parsing do CSV exportado SHALL produzir um objeto equivalente ao original (propriedade round-trip)
4. PARA TODOS os registros agregados válidos, fazer parsing do JSON exportado SHALL produzir um objeto equivalente ao original (propriedade round-trip)

### Requisito 13: [BACKLOG/TODO] Tela de detalhes do usuário com análise de uso

**User Story:** Como administrador, eu quero clicar no nome/ID de um usuário no dashboard e ver uma tela de detalhes com consumo diário, tendências e queries/prompts realizados, para que eu possa entender o comportamento dos usuários mais caros e otimizar custos de forma direcionada.

> ⚠️ **Este requisito está marcado como BACKLOG — será detalhado e implementado em uma fase futura.**

#### Notas e Ideias Gerais

- Ao clicar no UserId na tabela do Dashboard, abrir uma tela dedicada de detalhes do usuário
- Exibir consumo diário (créditos, mensagens, conversas) em formato de gráfico temporal
- Identificar e destacar os dias de maior uso do usuário
- Exibir tendências de consumo ao longo do tempo (crescimento, estabilidade, redução)
- Correlacionar dados de consumo com os logs de prompts/queries do usuário, integrando com os dados de prompt logging armazenados no S3
- Possibilidade de usar IA (ex: Amazon Bedrock) para analisar padrões de uso, identificar anomalias e gerar resumos automáticos do comportamento do usuário
- Objetivo principal: entender o que os usuários mais "caros" estão fazendo e se o consumo é justificado
- Pode envolver integração com um segundo Bucket S3 contendo os dados de prompt logging do Kiro
- Critérios de aceitação formais serão definidos quando este requisito for priorizado para implementação
