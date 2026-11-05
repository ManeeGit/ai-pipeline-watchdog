mock_provider "google" {
  mock_data "google_project" {
    defaults = { number = "123456789012" }
  }
}
variables {
  project_id      = "watchdog-test-project"
  billing_account = "000000-000000-000000"
  image_uri       = "us-central1-docker.pkg.dev/watchdog-test-project/images/watchdog@sha256:0000000000000000000000000000000000000000000000000000000000000000"
  alert_email     = "operator@example.com"
}
run "safe_defaults" {
  command = plan
  assert {
    condition     = !google_cloud_run_v2_service.dashboard.invoker_iam_disabled
    error_message = "Cloud Run must enforce invoker IAM."
  }
  assert {
    condition     = google_cloud_scheduler_job.scan.paused
    error_message = "The scheduler must start paused until deployment validation passes."
  }
  assert {
    condition     = google_cloud_run_v2_job.scanner.template[0].task_count == 1 && google_cloud_run_v2_job.scanner.template[0].parallelism == 1
    error_message = "The prototype is intentionally a single-task scanner."
  }
  assert {
    condition     = google_cloud_run_v2_service.dashboard.template[0].scaling[0].max_instance_count == 1
    error_message = "Dashboard scale must be capped to control costs."
  }
  assert {
    condition     = google_storage_bucket.state.public_access_prevention == "enforced"
    error_message = "Public bucket access must be prevented."
  }
  assert {
    condition     = length(google_cloud_run_v2_service_iam_member.operator) == 0
    error_message = "No dashboard identity should be granted implicitly."
  }
  assert {
    condition     = google_billing_budget.project.budget_filter[0].credit_types_treatment == "EXCLUDE_ALL_CREDITS"
    error_message = "Credits must not hide gross spend from budget alerts."
  }
}
run "reject_public_principal" {
  command = plan
  variables { dashboard_invokers = ["allUsers"] }
  expect_failures = [var.dashboard_invokers]
}
run "reject_mutable_image" {
  command = plan
  variables { image_uri = "us-central1-docker.pkg.dev/project/images/watchdog:latest" }
  expect_failures = [var.image_uri]
}
