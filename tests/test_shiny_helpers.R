#!/usr/bin/env Rscript

# Unit tests for Shiny helper functions used in workspace/source selection.

stopifnot <- function(...) {
  if (!all(...)) stop("Assertion failed", call. = FALSE)
}

assert_equal <- function(actual, expected, label = "") {
  if (!identical(actual, expected)) {
    stop(
      paste0(
        if (nzchar(label)) paste0(label, ": ") else "",
        "expected ", deparse(expected), " but got ", deparse(actual)
      ),
      call. = FALSE
    )
  }
}

assert_true <- function(condition, label = "") {
  if (!isTRUE(condition)) {
    stop(paste0(if (nzchar(label)) paste0(label, ": ") else "", "expected TRUE"), call. = FALSE)
  }
}

locate_repo_root <- function() {
  file_arg <- grep("^--file=", commandArgs(trailingOnly = FALSE), value = TRUE)
  if (length(file_arg) == 0) {
    return(normalizePath(file.path(getwd(), ".."), mustWork = FALSE))
  }
  script_path <- sub("^--file=", "", file_arg[[1]])
  normalizePath(file.path(dirname(script_path), ".."), mustWork = TRUE)
}

ROOT <- locate_repo_root()
source(file.path(ROOT, "shiny_app", "R", "helpers.R"), local = TRUE)

create_fixture_workspace <- function() {
  root <- tempfile("actintrack_workspace_")
  raw_dir <- file.path(root, "raw", "1_WT_218")
  dir.create(raw_dir, recursive = TRUE, showWarnings = FALSE)
  video_path <- file.path(raw_dir, "WT218_0001.avi")
  writeLines("fake avi placeholder", video_path)
  processed_dir <- file.path(root, "processed", "shiny_runs")
  dir.create(processed_dir, recursive = TRUE, showWarnings = FALSE)
  preview_path <- file.path(processed_dir, "sample_track_preview.mp4")
  writeLines("fake preview", preview_path)
  list(root = root, video_path = normalizePath(video_path, mustWork = FALSE))
}

run_tests <- function() {
  tests_run <- 0L
  run_case <- function(name, expr) {
    tests_run <<- tests_run + 1L
    result <- tryCatch(expr, error = function(exc) exc)
    if (inherits(result, "error")) {
      stop(paste0("[FAIL] ", name, ": ", conditionMessage(result)), call. = FALSE)
    }
    cat("[ok]", name, "\n")
  }

  fixture <- create_fixture_workspace()
  on.exit(unlink(fixture$root, recursive = TRUE, force = TRUE), add = TRUE)

  run_case("workspace_state marks valid project folders", {
    info <- workspace_state(fixture$root)
    assert_true(info$valid, "valid flag")
    assert_equal(info$status, "ready")
    assert_equal(info$path, normalize_project_path(fixture$root))
  })

  run_case("workspace_state marks missing folders", {
    info <- workspace_state(file.path(fixture$root, "missing"))
    assert_true(!info$valid, "missing folder")
    assert_equal(info$status, "missing")
  })

  run_case("discover_video_sources scopes to workspace only", {
    sources <- discover_video_sources(fixture$root)
    assert_true(nrow(sources) == 1L, "one source")
    assert_equal(sources$path[[1]], fixture$video_path)
    assert_equal(sources$group[[1]], "1_WT_218")
    assert_true(!any(grepl("_track_preview\\.mp4$", sources$file_name, ignore.case = TRUE)), "preview excluded")
  })

  run_case("discover_video_sources ignores other workspaces", {
    other <- tempfile("actintrack_other_")
    on.exit(unlink(other, recursive = TRUE, force = TRUE), add = TRUE)
    dir.create(file.path(other, "raw"), recursive = TRUE, showWarnings = FALSE)
    writeLines("x", file.path(other, "raw", "other.avi"))
    sources <- discover_video_sources(fixture$root)
    assert_true(all(startsWith(sources$path, normalize_project_path(fixture$root))), "scoped paths")
  })

  run_case("coerce_active_source_path keeps valid selection", {
    sources <- discover_video_sources(fixture$root)
    assert_equal(coerce_active_source_path(sources, fixture$video_path), fixture$video_path)
  })

  run_case("coerce_active_source_path replaces stale selection", {
    sources <- discover_video_sources(fixture$root)
    assert_equal(coerce_active_source_path(sources, "/tmp/missing.avi"), fixture$video_path)
  })

  run_case("coerce_active_source_path returns empty when no sources", {
    empty <- discover_video_sources(file.path(fixture$root, "missing"))
    assert_equal(coerce_active_source_path(empty, fixture$video_path), "")
  })

  run_case("format_video_probe_summary handles empty metadata", {
    summary <- format_video_probe_summary(NULL)
    assert_equal(summary$frame_count, "--")
    assert_equal(summary$dimensions, "--")
  })

  run_case("format_video_probe_summary formats probe payload", {
    summary <- format_video_probe_summary(list(frame_count = 12, width = 640, height = 480, playback_fps = 5.2))
    assert_equal(summary$frame_count, "12")
    assert_equal(summary$dimensions, "640 × 480 px")
    assert_equal(summary$playback_fps, "5.2")
  })

  tests_run
}

count <- run_tests()
cat(sprintf("\nAll %d Shiny helper tests passed.\n", count))
