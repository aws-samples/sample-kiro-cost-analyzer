# =============================================================================
# Makefile — Kiro Cost Analyzer
# Automação de deploy: infraestrutura (AWS SAM) + frontend (Amazon S3/Amazon CloudFront)
# =============================================================================

# Variáveis padrão (podem ser sobrescritas via linha de comando)
STACK_NAME ?= kiro-cost-analyzer
REGION ?= sa-east-1
AWS_PROFILE ?=

# Flag --profile condicional (vazia quando AWS_PROFILE não é informado)
PROFILE_FLAG := $(if $(AWS_PROFILE),--profile $(AWS_PROFILE),)

# Função auxiliar para extrair valores dos outputs do CloudFormation
# Uso: $(call get_output,NomeDoOutput)
define get_output
$(shell aws cloudformation describe-stacks \
	--stack-name $(STACK_NAME) \
	--region $(REGION) \
	$(PROFILE_FLAG) \
	--query "Stacks[0].Outputs[?OutputKey=='$(1)'].OutputValue" \
	--output text)
endef

# =============================================================================
# Targets principais
# =============================================================================

.PHONY: deploy deploy-infra deploy-frontend deploy-agentcore dev deploy-source-role deploy-identity-store-role

## Deploy completo: infraestrutura + frontend
deploy: deploy-infra deploy-frontend

## Deploy da infraestrutura via SAM (build + deploy)
## O samconfig.toml já contém todos os parâmetros necessários
deploy-infra:
	@echo "🔨 Construindo artefatos SAM..."
	sam build
	@echo "🚀 Fazendo deploy da infraestrutura..."
	sam deploy $(PROFILE_FLAG)

## Deploy do frontend: gera .env.production, builda, envia para S3 e invalida cache do CloudFront
deploy-frontend:
	$(eval WEBSITE_BUCKET := $(call get_output,WebsiteBucketName))
	$(eval CF_DIST_ID := $(call get_output,CloudFrontDistributionId))
	$(eval API_URL := $(call get_output,ApiUrl))
	$(eval USER_POOL_ID := $(call get_output,UserPoolId))
	$(eval CLIENT_ID := $(call get_output,UserPoolClientId))
	@echo "📝 Gerando frontend/.env.production a partir dos outputs do CloudFormation..."
	@echo "VITE_API_URL=$(API_URL)" > frontend/.env.production
	@echo "VITE_COGNITO_USER_POOL_ID=$(USER_POOL_ID)" >> frontend/.env.production
	@echo "VITE_COGNITO_CLIENT_ID=$(CLIENT_ID)" >> frontend/.env.production
	@echo "📦 Instalando dependências e construindo o frontend..."
	cd frontend && npm ci && npm run build
	@echo "☁️  Enviando arquivos para o S3 (bucket: $(WEBSITE_BUCKET))..."
	aws s3 sync frontend/dist/ s3://$(WEBSITE_BUCKET)/ --delete $(PROFILE_FLAG)
	@echo "🔄 Invalidando cache do CloudFront (distribuição: $(CF_DIST_ID))..."
	AWS_PAGER="" aws cloudfront create-invalidation --distribution-id $(CF_DIST_ID) --paths "/*" $(PROFILE_FLAG)
	@echo "✅ Deploy do frontend concluído!"
	@echo ""
	@echo "🌐 Acesse: https://$(call get_output,CloudFrontDomainName)"

## Deploy do agente de correlação Git-Kiro no Bedrock AgentCore
## Generates .bedrock_agentcore.yaml from template with real account data, then deploys.
AGENTCORE_AGENT_DIR := agent/app/GitCorrelationAgent

# Stable identity of the runtime. The AgentCore-generated runtime ID carries a
# volatile 10-char suffix (e.g. GitCorrelationAgent-nLdOow7N8j) that changes
# whenever the toolkit recreates the runtime. The NAME is the only stable,
# cross-account identifier, so we resolve the ARN by name after every deploy.
AGENTCORE_AGENT_NAME := GitCorrelationAgent

# Env prefix so the agentcore CLI (boto3-based) targets the same account/region
# as the rest of the deploy. Without this the CLI falls back to the default
# credential chain and can deploy into the wrong account.
AGENTCORE_ENV := $(if $(AWS_PROFILE),AWS_PROFILE=$(AWS_PROFILE) ,)AWS_REGION=$(REGION) AWS_DEFAULT_REGION=$(REGION)

deploy-agentcore:
	@command -v agentcore >/dev/null 2>&1 || { echo "❌ agentcore CLI not found. Install with: pip install bedrock-agentcore-starter-toolkit"; exit 1; }
	@if [ -z "$$VIRTUAL_ENV" ]; then \
		echo "⚠️  No virtual environment detected (VIRTUAL_ENV is unset)."; \
		echo "   The agentcore CLI and its dependencies may not be available."; \
		echo "   Activate your venv first: source .venv/bin/activate"; \
		exit 1; \
	fi
	$(eval ACCOUNT_ID := $(shell aws sts get-caller-identity --query Account --output text $(PROFILE_FLAG)))
	$(eval AGENT_ABS_DIR := $(shell cd $(AGENTCORE_AGENT_DIR) && pwd))
	@echo "🔧 Generating .bedrock_agentcore.yaml for account $(ACCOUNT_ID) in $(REGION)..."
	@sed -e 's|__ACCOUNT_ID__|$(ACCOUNT_ID)|g' \
	     -e 's|__REGION__|$(REGION)|g' \
	     -e 's|__AGENT_DIR__|$(AGENT_ABS_DIR)|g' \
	     -e 's|__STACK_NAME__|$(STACK_NAME)|g' \
	     $(AGENTCORE_AGENT_DIR)/.bedrock_agentcore.yaml.template > $(AGENTCORE_AGENT_DIR)/.bedrock_agentcore.yaml
	@echo "🤖 Deploying GitCorrelationAgent to Bedrock AgentCore (account $(ACCOUNT_ID), region $(REGION))..."
	cd $(AGENTCORE_AGENT_DIR) && $(AGENTCORE_ENV) agentcore deploy --auto-update-on-conflict
	@echo "✅ Agent deployed to AgentCore!"
	@echo "🔗 Resolving runtime ARN by name and syncing it into stack $(STACK_NAME)..."
	@set -e; \
	ARN=$$(aws bedrock-agentcore-control list-agent-runtimes \
		--region $(REGION) $(PROFILE_FLAG) \
		--query "agentRuntimes[?agentRuntimeName=='$(AGENTCORE_AGENT_NAME)'].agentRuntimeArn | [0]" \
		--output text); \
	if [ -z "$$ARN" ] || [ "$$ARN" = "None" ]; then \
		echo "❌ Could not find an AgentCore runtime named '$(AGENTCORE_AGENT_NAME)' in $(REGION)."; \
		echo "   The agent deploy above may have failed — check its output."; \
		exit 1; \
	fi; \
	echo "   Resolved: $$ARN"; \
	KEYS=$$(aws cloudformation describe-stacks --stack-name $(STACK_NAME) \
		--region $(REGION) $(PROFILE_FLAG) \
		--query "Stacks[0].Parameters[].ParameterKey" --output text); \
	if ! echo "$$KEYS" | tr '\t' '\n' | grep -qx CorrelationAgentRuntimeArn; then \
		echo "❌ Stack $(STACK_NAME) has no CorrelationAgentRuntimeArn parameter yet."; \
		echo "   Run 'make deploy-infra' first so the template that defines it is live."; \
		exit 1; \
	fi; \
	PARAMS=""; \
	for k in $$KEYS; do \
		if [ "$$k" = "CorrelationAgentRuntimeArn" ]; then \
			PARAMS="$$PARAMS ParameterKey=$$k,ParameterValue=$$ARN"; \
		else \
			PARAMS="$$PARAMS ParameterKey=$$k,UsePreviousValue=true"; \
		fi; \
	done; \
	echo "🚀 Updating stack (CorrelationAgentRuntimeArn only, all other params preserved)..."; \
	if OUT=$$(aws cloudformation update-stack --stack-name $(STACK_NAME) \
			--region $(REGION) $(PROFILE_FLAG) \
			--use-previous-template \
			--capabilities CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
			--parameters $$PARAMS 2>&1); then \
		echo "⏳ Waiting for stack update to complete..."; \
		aws cloudformation wait stack-update-complete --stack-name $(STACK_NAME) \
			--region $(REGION) $(PROFILE_FLAG); \
		echo "✅ Correlation worker now points at $$ARN"; \
	elif echo "$$OUT" | grep -q "No updates are to be performed"; then \
		echo "✅ Stack already points at $$ARN — nothing to update."; \
	else \
		echo "$$OUT"; \
		exit 1; \
	fi

## Inicia o servidor de desenvolvimento local do frontend
dev:
	cd frontend && npm run dev

# =============================================================================
# Deploy the cross-account IAM Role in the source account (S3 access)
# =============================================================================

# Variables for deploying the role in the source account
SOURCE_ACCOUNT_PROFILE ?=
KIRO_ACCOUNT_ID ?=
SOURCE_BUCKET_NAME ?=
KMS_KEY_ARN ?=
SOURCE_ROLE_STACK_NAME ?= kiro-cross-account-role

## Deploy the cross-account IAM Role in the source account (S3 access)
deploy-source-role:
ifndef SOURCE_ACCOUNT_PROFILE
	$(error SOURCE_ACCOUNT_PROFILE is required. Usage: make deploy-source-role SOURCE_ACCOUNT_PROFILE=profile KIRO_ACCOUNT_ID=123456789012 SOURCE_BUCKET_NAME=my-bucket)
endif
ifndef KIRO_ACCOUNT_ID
	$(error KIRO_ACCOUNT_ID is required. Usage: make deploy-source-role SOURCE_ACCOUNT_PROFILE=profile KIRO_ACCOUNT_ID=123456789012 SOURCE_BUCKET_NAME=my-bucket)
endif
ifndef SOURCE_BUCKET_NAME
	$(error SOURCE_BUCKET_NAME is required. Usage: make deploy-source-role SOURCE_ACCOUNT_PROFILE=profile KIRO_ACCOUNT_ID=123456789012 SOURCE_BUCKET_NAME=my-bucket)
endif
	@echo "🔐 Deploying cross-account IAM Role in the source account..."
	aws cloudformation deploy \
		--template-file source-account-role.yaml \
		--stack-name $(SOURCE_ROLE_STACK_NAME) \
		--capabilities CAPABILITY_NAMED_IAM \
		--profile $(SOURCE_ACCOUNT_PROFILE) \
		--parameter-overrides \
			KiroAccountId=$(KIRO_ACCOUNT_ID) \
			SourceBucketName=$(SOURCE_BUCKET_NAME) \
			KMSKeyArn=$(KMS_KEY_ARN)
	@echo "✅ Deploy complete. Role ARN:"
	@aws cloudformation describe-stacks \
		--stack-name $(SOURCE_ROLE_STACK_NAME) \
		--profile $(SOURCE_ACCOUNT_PROFILE) \
		--query "Stacks[0].Outputs[?OutputKey=='CrossAccountRoleArn'].OutputValue" \
		--output text
	@echo ""
	@echo "📋 Use this ARN in the main stack's SourceBucketRoleArn parameter, or paste it into the Settings page."

# =============================================================================
# Deploy the cross-account Identity Store IAM Role in the IDC account
# =============================================================================

# Variables for deploying the role in the IDC account
# NOTE: KIRO_ACCOUNT_ID is already declared above for deploy-source-role.
IDC_ACCOUNT_PROFILE ?=
IDENTITY_STORE_ID ?=
IDC_ROLE_STACK_NAME ?= kiro-identity-store-role

## Deploy the cross-account Identity Store IAM Role in the IDC account
deploy-identity-store-role:
ifndef IDC_ACCOUNT_PROFILE
	$(error IDC_ACCOUNT_PROFILE is required. Usage: make deploy-identity-store-role IDC_ACCOUNT_PROFILE=profile KIRO_ACCOUNT_ID=123456789012 [IDENTITY_STORE_ID=d-1234567890])
endif
ifndef KIRO_ACCOUNT_ID
	$(error KIRO_ACCOUNT_ID is required. Usage: make deploy-identity-store-role IDC_ACCOUNT_PROFILE=profile KIRO_ACCOUNT_ID=123456789012 [IDENTITY_STORE_ID=d-1234567890])
endif
	@echo "🔐 Deploying cross-account Identity Store IAM Role in the IDC account..."
	aws cloudformation deploy \
		--template-file identity-store-role.yaml \
		--stack-name $(IDC_ROLE_STACK_NAME) \
		--capabilities CAPABILITY_NAMED_IAM \
		--profile $(IDC_ACCOUNT_PROFILE) \
		--parameter-overrides \
			KiroAccountId=$(KIRO_ACCOUNT_ID) \
			IdentityStoreId=$(IDENTITY_STORE_ID)
	@echo "✅ Deploy complete. Role ARN:"
	@aws cloudformation describe-stacks \
		--stack-name $(IDC_ROLE_STACK_NAME) \
		--profile $(IDC_ACCOUNT_PROFILE) \
		--query "Stacks[0].Outputs[?OutputKey=='IdentityStoreRoleArn'].OutputValue" \
		--output text
	@echo ""
	@echo "📋 Use this ARN in the main stack's IdentityStoreRoleArn parameter, or paste it into the Settings page."

# =============================================================================
# Source archive for security scans
# =============================================================================

.PHONY: zip

## Generate a clean source-only zip for security scanning (no deps, no binaries)
zip:
	@rm -f kiro-cost-analyzer.zip
	@zip -r kiro-cost-analyzer.zip . \
		-x ".git/*" \
		-x ".aws-sam/*" \
		-x ".venv/*" \
		-x "node_modules/*" \
		-x "frontend/node_modules/*" \
		-x "frontend/dist/*" \
		-x "__pycache__/*" \
		-x "*/__pycache__/*" \
		-x ".hypothesis/*" \
		-x ".tmp-issues/*" \
		-x ".DS_Store" \
		-x "*/.DS_Store" \
		-x ".claude/*" \
		-x ".vscode/*" \
		-x "CLAUDE.md" \
		-x ".threatmodel/*" \
		-x ".repolinter/*" \
		-x ".kiro/*" \
		-x ".pytest_cache/*" \
		-x "frontend/.pytest_cache/*" \
		-x "output.log" \
		-x "agent/app/GitCorrelationAgent/.bedrock_agentcore/*" \
		-x "frontend/package-lock.json" \
		-x "frontend/src/assets/*.png" \
		-x "frontend/src/assets/*.svg" \
		-x "frontend/public/*.svg" \
		-x "docs/*.drawio" \
		-x "docs/*.bkp" \
		-x "docs/*.md" \
		-x ".tmp-issues/.*" \
		-x "shared/kca_shared.egg-info/*" \
		-x "samconfig.toml" \
		-x "frontend/.env.production" \
		-x "frontend/.env.local"
	@echo "✅ kiro-cost-analyzer.zip created ($$(du -h kiro-cost-analyzer.zip | cut -f1))"

# =============================================================================
# Data management
# =============================================================================

.PHONY: nuke-data reingest-data wipe-and-reingest

## Remove ALL data from DynamoDB tables and S3 DataBucket (preserves CloudFront logs)
## ⚠️  DESTRUCTIVE — requires confirmation
nuke-data:
	@echo "⚠️  WARNING: This will DELETE all data from:"
	@echo "   • DynamoDB: analytics, processed-files, user-names, feedback ($(STACK_NAME)-* in $(REGION))"
	@echo "   • S3: prompts-content/, etl-results/ in the DataBucket"
	@echo ""
	@read -p "Are you sure? Type 'yes' to confirm: " confirm && [ "$$confirm" = "yes" ] || { echo "❌ Aborted."; exit 1; }
	@echo ""
	@echo "🗑️  Removing all data..."
	REGION=$(REGION) STACK_NAME=$(STACK_NAME) python3 scripts/nuke_all_tables.py
	@echo "✅ All data removed."

## Trigger a fresh ETL run by starting the Step Functions state machine.
## The pipeline rebuilds DynamoDB analytics from the source bucket (CSVs + prompts).
reingest-data:
	@echo "🔍 Resolving caller account..."
	@ACCOUNT_ID=$$(aws sts get-caller-identity --query Account --output text $(PROFILE_FLAG)); \
	STATE_MACHINE_ARN="arn:aws:states:$(REGION):$$ACCOUNT_ID:stateMachine:$(STACK_NAME)-etl-state-machine"; \
	echo "🚀 Starting ETL state machine: $$STATE_MACHINE_ARN"; \
	EXEC_ARN=$$(aws stepfunctions start-execution \
		--state-machine-arn $$STATE_MACHINE_ARN \
		--region $(REGION) \
		$(PROFILE_FLAG) \
		--query 'executionArn' --output text); \
	echo "✅ Execution started: $$EXEC_ARN"; \
	echo ""; \
	echo "📊 Track progress at:"; \
	echo "   https://$(REGION).console.aws.amazon.com/states/home?region=$(REGION)#/v2/executions/details/$$EXEC_ARN"; \
	echo ""; \
	echo "Or poll the CLI:"; \
	echo "   aws stepfunctions describe-execution --execution-arn $$EXEC_ARN --region $(REGION) $(PROFILE_FLAG) --query 'status'"

## Full wipe + reingest cycle: nuke all data, then trigger a fresh ETL run.
## ⚠️  DESTRUCTIVE — requires confirmation (delegated to nuke-data).
wipe-and-reingest: nuke-data reingest-data
	@echo ""
	@echo "✅ Wipe-and-reingest cycle started. The Step Functions execution will"
	@echo "   rebuild analytics over the next several minutes — track it via the"
	@echo "   console URL printed above."
