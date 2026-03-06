variable "region" {
  default = "us-east-1"
}

# 1. Cognito User Pool for Inbound Authorization
resource "aws_cognito_user_pool" "financial_agent_pool" {
  name = "FinancialAgentUserPool"
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
resource "aws_s3_bucket" "financial_docs" {
  bucket = "amazon-financial-docs-kb-${random_string.suffix.result}"
}

# Basic configuration to hold the agent image
resource "aws_ecr_repository" "agent_repo" {
  name = "financial-agent-repo"
  # ECR Free tier gives 500MB/month free.
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
          Service = "bedrock.amazonaws.com"
        }
      }
    ]
  })
}

# 3. Agentcore Runtime (from task1.txt)
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
}
