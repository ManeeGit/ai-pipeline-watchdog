data "google_project" "current" { project_id = var.project_id }
locals {
  name = "pipeline-watchdog"
  apis = toset(["run.googleapis.com", "cloudscheduler.googleapis.com", "storage.googleapis.com", "logging.googleapis.com", "monitoring.googleapis.com", "billingbudgets.googleapis.com", "iam.googleapis.com"])
}
resource "google_project_service" "api" {
  for_each           = local.apis
  service            = each.value
  disable_on_destroy = false
}
resource "google_storage_bucket" "state" {
  name                        = "${var.project_id}-pipeline-watchdog-state"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  versioning { enabled = true }
  soft_delete_policy { retention_duration_seconds = 0 }
  lifecycle_rule {
    action { type = "Delete" }
    condition {
      with_state         = "ARCHIVED"
      num_newer_versions = 48
      matches_prefix     = ["state/"]
    }
  }
  depends_on = [google_project_service.api]
}
resource "google_service_account" "scanner" {
  account_id   = "watchdog-scanner"
  display_name = "Watchdog scanner, no keys"
  depends_on   = [google_project_service.api]
}
resource "google_service_account" "dashboard" {
  account_id   = "watchdog-dashboard"
  display_name = "Watchdog read-only dashboard, no keys"
  depends_on   = [google_project_service.api]
}
resource "google_service_account" "scheduler" {
  account_id   = "watchdog-scheduler"
  display_name = "Watchdog job invocation only"
  depends_on   = [google_project_service.api]
}
resource "google_project_iam_custom_role" "state_writer" {
  role_id     = "watchdogStateWriter"
  title       = "Watchdog conditional state writer"
  permissions = ["storage.objects.get", "storage.objects.create", "storage.objects.delete"]
}
resource "google_storage_bucket_iam_member" "scanner_state" {
  bucket = google_storage_bucket.state.name
  role   = google_project_iam_custom_role.state_writer.name
  member = "serviceAccount:${google_service_account.scanner.email}"
  condition {
    title      = "state-prefix-only"
    expression = "resource.name.startsWith('projects/_/buckets/${google_storage_bucket.state.name}/objects/state/')"
  }
}
resource "google_storage_bucket_iam_member" "scanner_inputs" {
  bucket = google_storage_bucket.state.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.scanner.email}"
  condition {
    title      = "inputs-prefix-only"
    expression = "resource.name.startsWith('projects/_/buckets/${google_storage_bucket.state.name}/objects/inputs/')"
  }
}
resource "google_storage_bucket_iam_member" "dashboard_state" {
  bucket = google_storage_bucket.state.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.dashboard.email}"
  condition {
    title      = "state-prefix-only"
    expression = "resource.name.startsWith('projects/_/buckets/${google_storage_bucket.state.name}/objects/state/')"
  }
}
resource "google_cloud_run_v2_job" "scanner" {
  name                = "${local.name}-scanner"
  location            = var.region
  deletion_protection = true
  template {
    task_count  = 1
    parallelism = 1
    template {
      service_account = google_service_account.scanner.email
      timeout         = "180s"
      max_retries     = 1
      containers {
        image   = var.image_uri
        command = ["python", "-m", "pipeline_watchdog.cloud"]
        args    = ["scan"]
        resources { limits = { cpu = "1", memory = "1Gi" } }
        env {
          name  = "WATCHDOG_BUCKET"
          value = google_storage_bucket.state.name
        }
        env {
          name  = "WATCHDOG_STATE_OBJECT"
          value = var.state_object
        }
        env {
          name  = "WATCHDOG_INPUT_MODE"
          value = var.input_mode
        }
        env {
          name  = "WATCHDOG_SCENARIO"
          value = var.scenario
        }
        env {
          name  = "WATCHDOG_RETENTION_DAYS"
          value = "30"
        }
      }
    }
  }
  depends_on = [google_storage_bucket_iam_member.scanner_state, google_storage_bucket_iam_member.scanner_inputs]
}
resource "google_cloud_run_v2_service" "dashboard" {
  invoker_iam_disabled = false
  name                 = "${local.name}-dashboard"
  location             = var.region
  deletion_protection  = true
  ingress              = "INGRESS_TRAFFIC_ALL"
  template {
    service_account                  = google_service_account.dashboard.email
    timeout                          = "60s"
    max_instance_request_concurrency = 4
    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }
    containers {
      image   = var.image_uri
      command = ["gunicorn"]
      args    = ["pipeline_watchdog.cloud:create_app()", "--bind=0.0.0.0:8080", "--workers=1", "--threads=4", "--timeout=55", "--max-requests=1000", "--max-requests-jitter=50", "--access-logfile=-"]
      ports { container_port = 8080 }
      resources {
        limits   = { cpu = "1", memory = "512Mi" }
        cpu_idle = true
      }
      env {
        name  = "WATCHDOG_BUCKET"
        value = google_storage_bucket.state.name
      }
      env {
        name  = "WATCHDOG_STATE_OBJECT"
        value = var.state_object
      }
      env {
        name  = "WATCHDOG_MAX_SCAN_AGE_SECONDS"
        value = "3900"
      }
      startup_probe {
        http_get {
          path = "/healthz"
          port = 8080
        }
        initial_delay_seconds = 0
        timeout_seconds       = 3
        period_seconds        = 5
        failure_threshold     = 12
      }
      liveness_probe {
        http_get {
          path = "/healthz"
          port = 8080
        }
        period_seconds    = 30
        timeout_seconds   = 3
        failure_threshold = 3
      }
    }
  }
  depends_on = [google_storage_bucket_iam_member.dashboard_state]
}
resource "google_cloud_run_v2_service_iam_member" "operator" {
  for_each = var.dashboard_invokers
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.dashboard.name
  role     = "roles/run.invoker"
  member   = each.value
}
resource "google_cloud_run_v2_job_iam_member" "scheduler" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.scanner.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler.email}"
}
resource "google_cloud_scheduler_job" "scan" {
  name             = "${local.name}-scan"
  region           = var.region
  schedule         = "*/30 * * * *"
  time_zone        = "Etc/UTC"
  paused           = var.scheduler_paused
  attempt_deadline = "60s"
  retry_config {
    retry_count          = 0
    max_retry_duration   = "0s"
    min_backoff_duration = "5s"
    max_backoff_duration = "60s"
    max_doublings        = 0
  }
  http_target {
    uri         = "https://run.googleapis.com/v2/projects/${var.project_id}/locations/${var.region}/jobs/${google_cloud_run_v2_job.scanner.name}:run"
    http_method = "POST"
    headers     = { "Content-Type" = "application/json" }
    body        = base64encode("{}")
    oauth_token {
      service_account_email = google_service_account.scheduler.email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }
  depends_on = [google_cloud_run_v2_job_iam_member.scheduler]
}
resource "google_monitoring_notification_channel" "operator" {
  display_name = "Watchdog operator"
  type         = "email"
  labels       = { email_address = var.alert_email }
  depends_on   = [google_project_service.api]
}
resource "google_billing_budget" "project" {
  billing_account = var.billing_account
  display_name    = "Watchdog gross-cost budget, not a hard cap"
  budget_filter {
    projects               = ["projects/${data.google_project.current.number}"]
    calendar_period        = "MONTH"
    credit_types_treatment = "EXCLUDE_ALL_CREDITS"
  }
  amount {
    specified_amount {
      currency_code = "USD"
      units         = tostring(var.monthly_budget_usd)
    }
  }
  dynamic "threshold_rules" {
    for_each = [0.5, 0.9, 1.0]
    content {
      threshold_percent = threshold_rules.value
      spend_basis       = "CURRENT_SPEND"
    }
  }
  all_updates_rule {
    monitoring_notification_channels = [google_monitoring_notification_channel.operator.id]
    disable_default_iam_recipients   = false
  }
  depends_on = [google_project_service.api]
}
resource "google_logging_metric" "scan_failures" {
  name   = "watchdog_cloud_scan_failures"
  filter = "resource.type=\"cloud_run_job\" resource.labels.job_name=\"${google_cloud_run_v2_job.scanner.name}\" jsonPayload.event=\"cloud_scan_failed\""
  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
  }
}
resource "google_logging_metric" "scan_commits" {
  name   = "watchdog_state_commits"
  filter = "resource.type=\"cloud_run_job\" resource.labels.job_name=\"${google_cloud_run_v2_job.scanner.name}\" jsonPayload.event=\"state_committed\""
  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
  }
}
resource "google_monitoring_alert_policy" "failure" {
  display_name          = "Watchdog scan failed"
  combiner              = "OR"
  notification_channels = [google_monitoring_notification_channel.operator.name]
  conditions {
    display_name = "Any scanner failure in five minutes"
    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.scan_failures.name}\" resource.type=\"cloud_run_job\""
      duration        = "0s"
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_SUM"
      }
    }
  }
}
resource "google_monitoring_alert_policy" "stale" {
  display_name          = "Watchdog has not committed state for 65 minutes"
  combiner              = "OR"
  notification_channels = [google_monitoring_notification_channel.operator.name]
  conditions {
    display_name = "Successful state commits absent"
    condition_absent {
      filter   = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.scan_commits.name}\" resource.type=\"cloud_run_job\""
      duration = "3900s"
      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_SUM"
      }
    }
  }
}
