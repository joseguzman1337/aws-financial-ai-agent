resource "aws_kms_key" "app_secrets" {
  description             = "KMS key used to encrypt sensitive application secrets"
  deletion_window_in_days = 7
  enable_key_rotation     = true
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "Enable IAM User Permissions"
        Effect = "Allow"
        Principal = {
          AWS = "arn:aws:iam::162187491349:root"
        }
        Action = [
          "kms:Create*",
          "kms:Describe*",
          "kms:Enable*",
          "kms:List*",
          "kms:Put*",
          "kms:Update*",
          "kms:Revoke*",
          "kms:Disable*",
          "kms:Get*",
          "kms:Delete*",
          "kms:TagResource",
          "kms:UntagResource",
          "kms:ScheduleKeyDeletion",
          "kms:CancelKeyDeletion",
          "kms:Encrypt",
          "kms:Decrypt",
          "kms:ReEncrypt*",
          "kms:GenerateDataKey*",
          "kms:DescribeKey"
        ]
        Resource = "*"
      },
      {
        Sid    = "Allow access for Key Administrators"
        Effect = "Allow"
        Principal = {
          AWS = "arn:aws:iam::162187491349:root"
        }
        Action = [
          "kms:Create*",
          "kms:Describe*",
          "kms:Enable*",
          "kms:List*",
          "kms:Put*",
          "kms:Update*",
          "kms:Revoke*",
          "kms:Disable*",
          "kms:Get*",
          "kms:Delete*",
          "kms:TagResource",
          "kms:UntagResource",
          "kms:ScheduleKeyDeletion",
          "kms:CancelKeyDeletion"
        ]
        Resource = "*"
      },
      {
        Sid    = "Allow use of the key"
        Effect = "Allow"
        Principal = {
          AWS = aws_iam_role.agentcore_execution_role.arn
        }
        Action = [
          "kms:Encrypt",
          "kms:Decrypt",
          "kms:ReEncrypt*",
          "kms:GenerateDataKey*",
          "kms:DescribeKey"
        ]
        Resource = "*"
      },
      {
        Sid    = "Allow CloudWatch Logs"
        Effect = "Allow"
        Principal = {
          Service = "logs.us-east-1.amazonaws.com"
        }
        Action = [
          "kms:Encrypt*",
          "kms:Decrypt*",
          "kms:ReEncrypt*",
          "kms:GenerateDataKey*",
          "kms:DescribeKey*"
        ]
        Resource = "*"
        Condition = {
          ArnLike = {
            "kms:EncryptionContext:aws:logs:arn" = "arn:aws:logs:us-east-1:162187491349:log-group:*"
          }
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

resource "aws_kms_alias" "app_secrets_alias" {
  name          = "alias/financial-ai-agent-secrets"
  target_key_id = aws_kms_key.app_secrets.key_id
}

resource "aws_ssm_parameter" "analyst_username" {
  name   = "/financial-ai/auth/analyst-username"
  type   = "SecureString"
  value  = "placeholder-replace-me"
  key_id = aws_kms_key.app_secrets.arn
  tags = {
    Project     = "FinancialAIAgent"
    Environment = "Development"
    ManagedBy   = "Terraform"
  }
}

resource "aws_ssm_parameter" "analyst_password" {
  name   = "/financial-ai/auth/analyst-password"
  type   = "SecureString"
  value  = "placeholder-replace-me"
  key_id = aws_kms_key.app_secrets.arn
  tags = {
    Project     = "FinancialAIAgent"
    Environment = "Development"
    ManagedBy   = "Terraform"
  }
}

resource "aws_ssm_parameter" "langfuse_public_key" {
  name   = "/financial-ai/langfuse/public-key"
  type   = "SecureString"
  value  = "placeholder-replace-me"
  key_id = aws_kms_key.app_secrets.arn
  tags = {
    Project     = "FinancialAIAgent"
    Environment = "Development"
    ManagedBy   = "Terraform"
  }
}

resource "aws_ssm_parameter" "langfuse_secret_key" {
  name   = "/financial-ai/langfuse/secret-key"
  type   = "SecureString"
  value  = "placeholder-replace-me"
  key_id = aws_kms_key.app_secrets.arn
  tags = {
    Project     = "FinancialAIAgent"
    Environment = "Development"
    ManagedBy   = "Terraform"
  }
}

resource "aws_ssm_parameter" "langchain_api_key_personal" {
  name   = "/financial-ai/langchain/personal-key"
  type   = "SecureString"
  value  = "placeholder-replace-me"
  key_id = aws_kms_key.app_secrets.arn
  tags = {
    Project     = "FinancialAIAgent"
    Environment = "Development"
    ManagedBy   = "Terraform"
  }
}

resource "aws_ssm_parameter" "langchain_api_key_service" {
  name   = "/financial-ai/langchain/service-key"
  type   = "SecureString"
  value  = "placeholder-replace-me"
  key_id = aws_kms_key.app_secrets.arn
  tags = {
    Project     = "FinancialAIAgent"
    Environment = "Development"
    ManagedBy   = "Terraform"
  }
}

resource "aws_ssm_parameter" "snyk_api_key" {
  name   = "/financial-ai/snyk/api-key"
  type   = "SecureString"
  value  = "placeholder-replace-me"
  key_id = aws_kms_key.app_secrets.arn
  tags = {
    Project     = "FinancialAIAgent"
    Environment = "Development"
    ManagedBy   = "Terraform"
  }
}

resource "aws_ssm_parameter" "infracost_api_key" {
  name   = "/financial-ai/infracost/api-key"
  type   = "SecureString"
  value  = "placeholder-replace-me"
  key_id = aws_kms_key.app_secrets.arn
  tags = {
    Project     = "FinancialAIAgent"
    Environment = "Development"
    ManagedBy   = "Terraform"
  }
}

resource "aws_ssm_parameter" "infracost_service_token" {
  name   = "/financial-ai/infracost/service-token"
  type   = "SecureString"
  value  = "placeholder-replace-me"
  key_id = aws_kms_key.app_secrets.arn
  tags = {
    Project     = "FinancialAIAgent"
    Environment = "Development"
    ManagedBy   = "Terraform"
  }
}
