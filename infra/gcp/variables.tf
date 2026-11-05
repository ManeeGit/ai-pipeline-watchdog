variable "project_id" {
  description = "An existing dedicated GCP project. No project is created by this template."
  type        = string
}
variable "billing_account" {
  description = "Existing billing account ID, required for project-scoped gross-cost alerts."
  type        = string
}
variable "region" {
  type    = string
  default = "us-central1"
}
variable "image_uri" {
  description = "Already-built Artifact Registry image pinned by immutable sha256 digest."
  type        = string
  validation {
    condition     = can(regex("^[a-z0-9-]+-docker\\.pkg\\.dev/.+@sha256:[a-f0-9]{64}$", var.image_uri))
    error_message = "Use an immutable Artifact Registry image digest, not a mutable tag."
  }
}
variable "alert_email" {
  description = "Explicit operator email for monitoring and budget notifications. Must be verified after deployment."
  type        = string
}
variable "dashboard_invokers" {
  description = "Explicit user:, group:, or serviceAccount: identities. Empty grants nobody access. Public principals are rejected."
  type        = set(string)
  default     = []
  validation {
    condition     = alltrue([for principal in var.dashboard_invokers : can(regex("^(user|group|serviceAccount):[^ ]+$", principal))])
    error_message = "Only explicit authenticated principals are permitted; never allUsers/allAuthenticatedUsers."
  }
}
variable "input_mode" {
  type    = string
  default = "synthetic"
  validation {
    condition     = contains(["synthetic", "gcs"], var.input_mode)
    error_message = "Choose synthetic or gcs; real data requires a separate authorized ingestion decision."
  }
}
variable "scenario" {
  type    = string
  default = "healthy"
  validation {
    condition     = contains(["healthy", "late-arrival", "schema-drift", "quality-regression", "volume-drop", "run-failure", "cascade"], var.scenario)
    error_message = "Unknown synthetic scenario."
  }
}
variable "monthly_budget_usd" {
  type    = number
  default = 10
  validation {
    condition     = var.monthly_budget_usd >= 1 && var.monthly_budget_usd <= 50 && floor(var.monthly_budget_usd) == var.monthly_budget_usd
    error_message = "Choose an integer 1–50 USD budget. This is an alert, not a spending cap."
  }
}
variable "scheduler_paused" {
  description = "Starts paused. Enable only after the manual deployment acceptance checks pass."
  type        = bool
  default     = true
}

variable "state_object" {
  description = "Versioned contract/state identity. Changing a contract requires a reviewed new state object."
  type        = string
  default     = "state/watchdog.bundle"
  validation {
    condition     = can(regex("^state/[A-Za-z0-9_-]+[.]bundle$", var.state_object))
    error_message = "Use state/<identifier>.bundle; traversal and other prefixes are not permitted."
  }
}
