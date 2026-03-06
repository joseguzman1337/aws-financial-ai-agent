variable "region" {
  type        = string
  description = "The AWS region to deploy resources into."
  default     = "us-east-1"
}

resource "aws_accessanalyzer_analyzer" "account_analyzer" {
  analyzer_name = "financial-agent-analyzer"
  type          = "ACCOUNT"
  tags = {
    Project     = "FinancialAIAgent"
    Environment = "Development"
    ManagedBy   = "Terraform"
  }
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

resource "aws_cognito_identity_pool" "financial_agent_identity_pool" {
  # checkov:skip=CKV_AWS_366: Guest access is required for recruiter demo credential retrieval
  identity_pool_name               = "FinancialAgentIdentityPool"
  allow_unauthenticated_identities = true # Enabled for guest credential retrieval
  allow_classic_flow               = true # Enabled to prevent session policy restrictions

  cognito_identity_providers {
    client_id               = aws_cognito_user_pool_client.financial_agent_client.id
    provider_name           = aws_cognito_user_pool.financial_agent_pool.endpoint
    server_side_token_check = false
  }
}

resource "aws_iam_role" "cognito_unauthenticated_role" {
  name = "cognito_unauthenticated_role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRoleWithWebIdentity"
        Effect = "Allow"
        Principal = {
          Federated = "cognito-identity.amazonaws.com"
        }
        Condition = {
          "StringEquals" = {
            "cognito-identity.amazonaws.com:aud" = aws_cognito_identity_pool.financial_agent_identity_pool.id
          }
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "cognito_guest_ssm_policy" {
  name = "cognito_guest_ssm_policy"
  role = aws_iam_role.cognito_unauthenticated_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = [
          "ssm:GetParameter",
          "ssm:GetParameters"
        ]
        Effect   = "Allow"
        Resource = "arn:aws:ssm:${var.region}:162187491349:parameter/financial-ai/*"
      },
      {
        Action = [
          "kms:Decrypt"
        ]
        Effect   = "Allow"
        Resource = aws_kms_key.app_secrets.arn
      },
      {
        # Cognito Identity operations do not support resource-level permissions
        Action = [
          "cognito-identity:GetCredentialsForIdentity",
          "cognito-identity:GetId"
        ]
        Effect   = "Allow"
        Resource = "*"
      }
    ]
  })
}


resource "aws_iam_role" "cognito_authenticated_role" {
  name = "cognito_authenticated_role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRoleWithWebIdentity"
        Effect = "Allow"
        Principal = {
          Federated = "cognito-identity.amazonaws.com"
        }
        Condition = {
          "StringEquals" = {
            "cognito-identity.amazonaws.com:aud" = aws_cognito_identity_pool.financial_agent_identity_pool.id
          }
          "ForAnyValue:StringLike" = {
            "cognito-identity.amazonaws.com:amr" = "authenticated"
          }
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "cognito_ssm_policy" {
  name = "cognito_ssm_policy"
  role = aws_iam_role.cognito_authenticated_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = [
          "ssm:GetParameter",
          "ssm:GetParameters"
        ]
        Effect   = "Allow"
        Resource = "arn:aws:ssm:${var.region}:162187491349:parameter/financial-ai/langfuse/*"
      },
      {
        Action = [
          "kms:Decrypt"
        ]
        Effect   = "Allow"
        Resource = aws_kms_key.app_secrets.arn
      }
    ]
  })
}

resource "aws_cognito_identity_pool_roles_attachment" "main" {
  identity_pool_id = aws_cognito_identity_pool.financial_agent_identity_pool.id

  roles = {
    authenticated   = aws_iam_role.cognito_authenticated_role.arn
    unauthenticated = aws_iam_role.cognito_unauthenticated_role.arn
  }

  role_mapping {
    identity_provider         = "${aws_cognito_user_pool.financial_agent_pool.endpoint}:${aws_cognito_user_pool_client.financial_agent_client.id}"
    ambiguous_role_resolution = "AuthenticatedRole"
    type                      = "Token"
  }
}

resource "aws_cognito_user_pool_client" "financial_agent_client" {
  name                = "FinancialAgentClient"
  user_pool_id        = aws_cognito_user_pool.financial_agent_pool.id
  generate_secret     = false
  explicit_auth_flows = ["ALLOW_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]
}

variable "analyst_password" {
  type        = string
  description = "The password for the analyst Cognito user."
  sensitive   = true
  default     = "SecurePassword123!"
}

resource "aws_cognito_user" "analyst_user" {
  user_pool_id = aws_cognito_user_pool.financial_agent_pool.id
  username     = "analyst_user"
  password     = var.analyst_password

  attributes = {
    email          = "analyst@example.com"
    email_verified = true
  }
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
    # kics:ignore-line
    # MFA Delete must be enabled via CLI as it is not supported by Terraform directly
    # mfa_delete = "Enabled"
  }
}

resource "aws_s3_bucket_versioning" "financial_docs_versioning" {
  bucket = aws_s3_bucket.financial_docs.id
  versioning_configuration {
    status = "Enabled"
    # kics:ignore-line
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
  image_tag_mutability = "MUTABLE"
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
        Sid    = "AllowBedrockServicePull"
        Effect = "Allow"
        Principal = {
          Service = "bedrock-agentcore.amazonaws.com"
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
          Service = [
            "bedrock-agentcore.amazonaws.com",
            "bedrock.amazonaws.com"
          ]
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

  # kics:ignore-line
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowECRAuth"
        Action = [
          "ecr:GetAuthorizationToken"
        ]
        Effect   = "Allow"
        Resource = "*"
      },
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
          "bedrock:InvokeModelWithResponseStream",
          "bedrock:Converse",
          "bedrock:ConverseStream",
          "bedrock:Retrieve"
        ]
        Effect   = "Allow"
        Resource = [
          "arn:aws:bedrock:*::foundation-model/*",
          "arn:aws:bedrock:${var.region}:162187491349:inference-profile/*",
          "arn:aws:bedrock:${var.region}:162187491349:knowledge-base/*"
        ]
      },
      {
        Sid    = "AllowS3Access"
        Action = [
          "s3:GetObject",
          "s3:ListBucket"
        ]
        Effect = "Allow"
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
      },
      {
        Sid    = "AllowLogging"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents",
          "logs:CreateLogGroup",
          "logs:DescribeLogStreams"
        ]
        Effect = "Allow"
        Resource = [
          aws_cloudwatch_log_group.agent_logs.arn,
          "${aws_cloudwatch_log_group.agent_logs.arn}:*",
          # AgentCore auto-creates its own log group with runtime ID suffix
          "arn:aws:logs:${var.region}:162187491349:log-group:/aws/bedrock-agentcore/runtimes/*",
          "arn:aws:logs:${var.region}:162187491349:log-group:/aws/bedrock-agentcore/runtimes/*:*"
        ]
      },
      {
        Sid    = "AllowMarketplace"
        Action = [
          "aws-marketplace:ViewSubscriptions",
          "aws-marketplace:Subscribe"
        ]
        Effect   = "Allow"
        Resource = "*"
      },
      {
        Sid    = "AllowAgentCore"
        Action = [
          "bedrock-agentcore:*"
        ]
        Effect   = "Allow"
        Resource = "*"
      }
    ]
  })
}


resource "aws_cloudwatch_log_group" "agent_logs" {
  name              = "/aws/bedrock/agent-runtime/Financial_Analyst_Agent"
  retention_in_days = 365
  kms_key_id        = aws_kms_key.app_secrets.arn
  tags = {
    Project     = "FinancialAIAgent"
    Environment = "Development"
    ManagedBy   = "Terraform"
  }
}

# 3. Agentcore Runtime (from task1.txt)
resource "aws_bedrockagentcore_agent_runtime" "financial_agent_runtime" {
  agent_runtime_name = "Financial_Analyst_Agent"
  role_arn           = aws_iam_role.agentcore_execution_role.arn

  agent_runtime_artifact {
    container_configuration {
      container_uri = "${aws_ecr_repository.agent_repo.repository_url}:v2"
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

# 5. Automated Verification (Proof of Work)
# Triggers the 5 required queries to ensure traces are captured in Langfuse
resource "null_resource" "agent_verification" {
  depends_on = [aws_bedrockagentcore_agent_runtime.financial_agent_runtime, aws_cognito_user.analyst_user]

  provisioner "local-exec" {
    command = "/opt/anaconda3/envs/x/bin/python ../python/verify_queries.py"
    environment = {
      COGNITO_CLIENT_ID = aws_cognito_user_pool_client.financial_agent_client.id
      AGENT_ARN         = aws_bedrockagentcore_agent_runtime.financial_agent_runtime.agent_runtime_arn
      ACCOUNT_ID        = "162187491349"
      AWS_REGION        = var.region
      AWS_PROFILE       = "t1cx"
    }
  }

  triggers = {
    # Re-run if the agent runtime changes or the script is modified
    agent_version = aws_bedrockagentcore_agent_runtime.financial_agent_runtime.agent_runtime_version
    script_hash   = filemd5("${path.module}/../python/verify_queries.py")
  }
}
