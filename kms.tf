resource "aws_kms_key" "app_secrets" {
  description             = "KMS key used to encrypt sensitive application secrets"
  deletion_window_in_days = 7
  enable_key_rotation     = true
}

resource "aws_kms_alias" "app_secrets_alias" {
  name          = "alias/financial-ai-agent-secrets"
  target_key_id = aws_kms_key.app_secrets.key_id
}

# Native Terraform Data Sources to dynamically read the securely stored keys at deploy-time
data "aws_ssm_parameter" "langfuse_public_key" {
  name = "/financial-ai/langfuse/public-key"
}

data "aws_ssm_parameter" "langfuse_secret_key" {
  name = "/financial-ai/langfuse/secret-key"
}

data "aws_ssm_parameter" "langchain_api_key_personal" {
  name = "/financial-ai/langchain/personal-key"
}

data "aws_ssm_parameter" "langchain_api_key_service" {
  name = "/financial-ai/langchain/service-key"
}
