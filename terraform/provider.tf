terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.63.0" # latest used
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.9.0"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.3.0"
    }
  }
}

provider "aws" {
  region  = "us-east-1"
  profile = "t1cx"
}
