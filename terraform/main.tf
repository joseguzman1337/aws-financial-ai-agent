variable "region" {
  type        = string
  description = "The AWS region to deploy resources into."
  default     = "us-east-1"
}

# 1. Cognito User Pool for Inbound Authorization
resource "aws_cognito_user_pool" "financial_agent_pool" {
  name = "FinancialAgentUserPool"

  mfa_configuration = "OPTIONAL" # Added to resolve LOW finding
  software_token_mfa_configuration {
    enabled = true
  }

  tags = {
    Project     = "FinancialAIAgent"
    Environment = "Development"
    ManagedBy   = "Terraform"
  }
}

resource "aws_cognito_user_pool_client" "financial_agent_client" {
  name                = "FinancialAgentClient"
  user_pool_id        = aws_cognito_user_pool.financial_agent_pool.id
  generate_secret     = false
  explicit_auth_flows = ["ALLOW_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]
}

# Random suffix to avoid bucket naming collisions
resource "random_string" "suffix" {
  length  = 8
  special = false
  upper   = false
}

# 2. Bedrock Knowledge Base (S3 bucket, free tier eligible)
resource "aws_s3_bucket" "financial_docs_logging" {
  bucket = "amazon-financial-docs-logs-${random_string.suffix.result}"
  tags = {
    Project     = "FinancialAIAgent"
    Environment = "Development"
    ManagedBy   = "Terraform"
  }
  }


resource "aws_s3_bucket" "financial_docs" {
  bucket = "amazon-financial-docs-kb-${random_string.suffix.result}"
  tags = {
    Project     = "FinancialAIAgent"
    Environment = "Development"
    ManagedBy   = "Terraform"
  }
  }


resource "aws_s3_bucket_logging" "financial_docs_logging" {
  bucket = aws_s3_bucket.financial_docs.id

  target_bucket = aws_s3_bucket.financial_docs_logging.id
  target_prefix = "log/"
}

resource "aws_s3_bucket_versioning" "financial_docs_logging_versioning" {
  bucket = aws_s3_bucket.financial_docs_logging.id
  versioning_configuration {
    status = "Enabled"
    # MFA Delete must be enabled via CLI as it is not supported by Terraform directly
    # mfa_delete = "Enabled"
  }
}

resource "aws_s3_bucket_versioning" "financial_docs_versioning" {
  bucket = aws_s3_bucket.financial_docs.id
  versioning_configuration {
    status = "Enabled"
    # MFA Delete must be enabled via CLI as it is not supported by Terraform directly
    # mfa_delete = "Enabled"
  }
}

resource "aws_s3_object" "financial_docs_upload" {
  for_each = fileset("${path.module}/docs", "*.pdf")
  bucket   = aws_s3_bucket.financial_docs.id
  key      = each.value
  source   = "${path.module}/docs/${each.value}"
  etag     = filemd5("${path.module}/docs/${each.value}")
  tags = {
    Project     = "FinancialAIAgent"
    Environment = "Development"
    ManagedBy   = "Terraform"
  }
}

# Basic configuration to hold the agent image
resource "aws_ecr_repository" "agent_repo" {
  name                 = "financial-agent-repo"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = true

  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.app_secrets.arn
  }

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Project     = "FinancialAIAgent"
    Environment = "Development"
    ManagedBy   = "Terraform"
  }
}

resource "aws_ecr_repository_policy" "agent_repo_policy" {
  repository = aws_ecr_repository.agent_repo.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowAgentPull"
        Effect = "Allow"
        Principal = {
          AWS = aws_iam_role.agentcore_execution_role.arn
        }
        Action = [
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer"
        ]
      }
    ]
  })
}

resource "aws_iam_role" "agentcore_execution_role" {
  name = "agentcore_execution_role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "bedrock-agentcore.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Project     = "FinancialAIAgent"
    Environment = "Development"
    ManagedBy   = "Terraform"
  }
}


resource "aws_iam_role_policy" "agentcore_execution_policy" {
  name = "agentcore_execution_policy"
  role = aws_iam_role.agentcore_execution_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowECRPull"
        Action = [
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer"
        ]
        Effect   = "Allow"
        Resource = aws_ecr_repository.agent_repo.arn
      },
      {
        Sid    = "AllowBedrockInvoke"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:Retrieve"
        ]
        Effect   = "Allow"
        Resource = "*"
      },
      {
        Sid    = "AllowS3Access"
        Action = [
          "s3:GetObject",
          "s3:ListBucket"
        ]
        Effect   = "Allow"
        Resource = [
          aws_s3_bucket.financial_docs.arn,
          "${aws_s3_bucket.financial_docs.arn}/*"
        ]
      },
      {
        Sid    = "AllowSSMRead"
        Action = [
          "ssm:GetParameter",
          "ssm:GetParameters"
        ]
        Effect   = "Allow"
        Resource = "arn:aws:ssm:${var.region}:162187491349:parameter/financial-ai/*"
      },
      {
        Sid    = "AllowKMSDecrypt"
        Action = [
          "kms:Decrypt"
        ]
        Effect   = "Allow"
        Resource = aws_kms_key.app_secrets.arn
      }
    ]
  })
}


# 3. Bedrock Knowledge Base (from task1.txt)
# Note: Full OpenSearch Serverless collection skipped as per task1.txt assumption note
# This resource represents the KB definition itself.
resource "aws_bedrockagent_knowledge_base" "financial_kb" {
  name     = "AmazonFinancialDocsKB"
  role_arn = aws_iam_role.agentcore_execution_role.arn

  knowledge_base_configuration {
    type = "VECTOR"
    vector_knowledge_base_configuration {
      embedding_model_arn = "arn:aws:bedrock:${var.region}::foundation-model/amazon.titan-embed-text-v1"
    }
  }

  storage_configuration {
    type = "OPENSEARCH_SERVERLESS"
    opensearch_serverless_configuration {
      collection_arn    = "arn:aws:managed:collection" # Placeholder
      vector_index_name = "bedrock-knowledge-base-default-index"
      field_mapping {
        vector_field   = "bedrock-knowledge-base-default-vector"
        text_field     = "AMAZON_BEDROCK_TEXT_CHUNK"
        metadata_field = "AMAZON_BEDROCK_METADATA"
      }
    }
  }

  tags = {
    Project     = "FinancialAIAgent"
    Environment = "Development"
    ManagedBy   = "Terraform"
  }
}

resource "aws_bedrockagent_data_source" "financial_ds" {
  knowledge_base_id = aws_bedrockagent_knowledge_base.financial_kb.id
  name              = "FinancialDocsDataSource"
  data_source_configuration {
    type = "S3"
    s3_configuration {
      bucket_arn = aws_s3_bucket.financial_docs.arn
    }
  }
}

# 4. Agentcore Runtime (from task1.txt)
resource "aws_bedrockagentcore_agent_runtime" "financial_agent_runtime" {
  agent_runtime_name = "Financial_Analyst_Agent"
  role_arn           = aws_iam_role.agentcore_execution_role.arn

  agent_runtime_artifact {
    container_configuration {
      container_uri = "${aws_ecr_repository.agent_repo.repository_url}:latest"
    }
  }


  network_configuration {
    network_mode = "PUBLIC" # Public to utilize Free Tier as much as possible, avoiding VPC peering costs
  }

  # Custom JWT authorizer pointing to the Cognito Discovery URL
  authorizer_configuration {
    custom_jwt_authorizer {
      discovery_url   = "https://cognito-idp.${var.region}.amazonaws.com/${aws_cognito_user_pool.financial_agent_pool.id}/.well-known/openid-configuration"
      allowed_clients = [aws_cognito_user_pool_client.financial_agent_client.id]
    }
  }

  tags = {
    Project     = "FinancialAIAgent"
    Environment = "Development"
    ManagedBy   = "Terraform"
  }
}
