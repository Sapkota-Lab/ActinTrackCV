`%||%` <- function(x, y) {
  if (is.null(x) || length(x) == 0 || all(is.na(x)) || identical(x, "")) y else x
}

safe_numeric <- function(x) {
  suppressWarnings(as.numeric(x))
}

safe_mean <- function(x) {
  values <- safe_numeric(x)
  if (length(values) == 0 || all(is.na(values))) return(NA_real_)
  mean(values, na.rm = TRUE)
}

format_metric <- function(value, digits = 3) {
  value <- safe_numeric(value)
  if (length(value) == 0 || is.na(value[[1]])) return("--")
  formatC(value[[1]], digits = digits, format = "f")
}

format_bytes <- function(bytes) {
  bytes <- safe_numeric(bytes)
  if (length(bytes) == 0 || is.na(bytes[[1]])) return("--")
  units <- c("B", "KB", "MB", "GB", "TB")
  power <- if (bytes[[1]] <= 0) 0 else min(floor(log(bytes[[1]], 1024)), length(units) - 1)
  paste0(formatC(bytes[[1]] / (1024 ^ power), digits = 1, format = "f"), " ", units[[power + 1]])
}

normalize_project_path <- function(path) {
  normalizePath(path.expand(trimws(path)), mustWork = FALSE)
}

relative_to_project <- function(project_dir, path) {
  project <- paste0(normalize_project_path(project_dir), .Platform$file.sep)
  normalized <- normalizePath(path, mustWork = FALSE)
  if (startsWith(normalized, project)) substring(normalized, nchar(project) + 1) else normalized
}

resolve_result_path <- function(project_dir, value) {
  value <- trimws(as.character(value %||% ""))
  if (!nzchar(value)) return("")
  if (grepl("^(/|[A-Za-z]:[\\\\/])", value)) return(value)
  normalizePath(file.path(project_dir, value), mustWork = FALSE)
}

infer_group_from_path <- function(project_dir, path) {
  relative <- relative_to_project(project_dir, path)
  parts <- strsplit(relative, .Platform$file.sep, fixed = TRUE)[[1]]
  known <- c("1_WT_218", "2_WT_550", "3_Mutant_515", "4_Mutant_175")
  match <- parts[parts %in% known]
  if (length(match) > 0) match[[1]] else "Unassigned"
}

discover_video_sources <- function(project_dir) {
  project_dir <- normalize_project_path(project_dir)
  if (!dir.exists(project_dir)) return(data.frame())
  search_roots <- file.path(project_dir, c("raw", "processed"))
  search_roots <- search_roots[dir.exists(search_roots)]
  if (length(search_roots) == 0) return(data.frame())
  paths <- unlist(lapply(search_roots, function(root) {
    list.files(
      root,
      pattern = "\\.(avi|mp4)$",
      recursive = TRUE,
      full.names = TRUE,
      ignore.case = TRUE
    )
  }), use.names = FALSE)
  paths <- paths[!grepl("_track_preview\\.mp4$", paths, ignore.case = TRUE)]
  paths <- sort(unique(normalizePath(paths, mustWork = FALSE)))
  if (length(paths) == 0) return(data.frame())
  info <- file.info(paths)
  relative <- vapply(paths, function(path) relative_to_project(project_dir, path), character(1))
  location <- vapply(strsplit(relative, .Platform$file.sep, fixed = TRUE), function(parts) parts[[1]], character(1))
  groups <- vapply(paths, function(path) infer_group_from_path(project_dir, path), character(1))
  data.frame(
    source_id = as.character(seq_along(paths)),
    file_name = basename(paths),
    group = groups,
    location = location,
    size_bytes = info$size,
    size = vapply(info$size, format_bytes, character(1)),
    modified = format(info$mtime, "%Y-%m-%d %H:%M"),
    relative_path = relative,
    path = paths,
    stringsAsFactors = FALSE,
    row.names = NULL
  )
}

source_choices <- function(sources) {
  if (is.null(sources) || nrow(sources) == 0) return(character())
  labels <- paste(sources$group, sources$file_name, sep = "  /  ")
  stats::setNames(sources$path, labels)
}

workspace_state <- function(project_dir) {
  path <- normalize_project_path(project_dir)
  valid <- dir.exists(path)
  list(
    path = path,
    valid = isTRUE(valid),
    status = if (isTRUE(valid)) "ready" else "missing",
    message = if (isTRUE(valid)) "Workspace ready" else "Folder not found"
  )
}

coerce_active_source_path <- function(sources, current_path = "") {
  current_path <- trimws(as.character(current_path %||% ""))
  if (is.null(sources) || nrow(sources) == 0) return("")
  if (nzchar(current_path) && current_path %in% sources$path) return(current_path)
  sources$path[[1]]
}

source_file_choice_label <- function(row, is_active = FALSE) {
  htmltools::div(
    class = paste("source-file-row", if (isTRUE(is_active)) "is-active"),
    htmltools::div(class = "source-file-icon", fontawesome::fa("file-video", height = "14px")),
    htmltools::div(
      class = "source-file-copy",
      htmltools::strong(row$file_name),
      htmltools::tags$small(paste(row$group, "·", row$location))
    ),
    htmltools::div(
      class = "source-file-meta",
      htmltools::span(row$size),
      htmltools::tags$small(row$modified)
    )
  )
}

format_video_probe_summary <- function(metadata) {
  if (is.null(metadata) || length(metadata) == 0) {
    return(list(
      frame_count = "--",
      dimensions = "--",
      playback_fps = "--"
    ))
  }
  list(
    frame_count = as.character(metadata$frame_count %||% "--"),
    dimensions = paste0(metadata$width %||% "--", " × ", metadata$height %||% "--", " px"),
    playback_fps = format_metric(metadata$playback_fps, 1)
  )
}

active_source_banner <- function(row, metadata = NULL, empty_message = "Select a video from the list.") {
  if (is.null(row)) {
    return(htmltools::div(
      class = "active-source-banner active-source-banner-empty",
      fontawesome::fa("circle-question", height = "18px"),
      htmltools::div(
        htmltools::strong("No active video"),
        htmltools::p(empty_message)
      )
    ))
  }
  summary <- format_video_probe_summary(metadata)
  htmltools::div(
    class = "active-source-banner",
    htmltools::div(class = "active-source-icon", fontawesome::fa("film", height = "18px")),
    htmltools::div(
      class = "active-source-copy",
      htmltools::div(class = "active-source-label", "ACTIVE VIDEO"),
      htmltools::strong(row$file_name),
      htmltools::p(row$relative_path)
    ),
    htmltools::div(
      class = "active-source-tags",
      htmltools::span(class = "active-source-tag", row$group),
      htmltools::span(class = "active-source-tag", toupper(tools::file_ext(row$file_name))),
      htmltools::span(class = "active-source-tag", row$size),
      htmltools::span(class = "active-source-tag", paste0(summary$frame_count, " frames")),
      htmltools::span(class = "active-source-tag", summary$dimensions)
    )
  )
}

discover_z_stacks <- function(project_dir) {
  project_dir <- normalize_project_path(project_dir)
  if (!dir.exists(project_dir)) return(data.frame())
  paths <- list.files(
    project_dir,
    pattern = "\\.(oir|oib|tif|tiff)$",
    recursive = TRUE,
    full.names = TRUE,
    ignore.case = TRUE,
    include.dirs = FALSE
  )
  paths <- sort(unique(normalizePath(paths, mustWork = FALSE)))
  if (length(paths) == 0) return(data.frame())
  info <- file.info(paths)
  data.frame(
    stack_id = as.character(seq_along(paths)),
    file_name = basename(paths),
    group = vapply(paths, function(path) infer_group_from_path(project_dir, path), character(1)),
    extension = toupper(tools::file_ext(paths)),
    size = vapply(info$size, format_bytes, character(1)),
    size_bytes = info$size,
    modified = format(info$mtime, "%Y-%m-%d %H:%M"),
    relative_path = vapply(paths, function(path) relative_to_project(project_dir, path), character(1)),
    path = paths,
    stringsAsFactors = FALSE,
    row.names = NULL
  )
}

bridge_python <- function(project_dir) {
  candidates <- c(
    file.path(project_dir, ".venv", "bin", "python"),
    file.path(project_dir, "venv", "bin", "python"),
    Sys.which("python3")
  )
  candidates <- candidates[nzchar(candidates) & file.exists(candidates)]
  if (length(candidates) == 0) stop("No Python interpreter was found for the tracking bridge.")
  candidates[[1]]
}

run_bridge <- function(project_dir, arguments) {
  project_dir <- normalize_project_path(project_dir)
  script <- file.path(project_dir, "scripts", "shiny_bridge.py")
  if (!file.exists(script)) stop("Missing scripts/shiny_bridge.py in the selected project.")
  command <- bridge_python(project_dir)
  args <- c(shQuote(script), vapply(as.character(arguments), shQuote, character(1)))
  output <- system2(command, args, stdout = TRUE, stderr = TRUE)
  status <- attr(output, "status") %||% 0L
  json_lines <- output[grepl("^\\{.*\\}$", output)]
  payload <- if (length(json_lines) > 0) {
    jsonlite::fromJSON(tail(json_lines, 1), simplifyVector = FALSE)
  } else {
    list(ok = FALSE, error = paste(output, collapse = "\n"))
  }
  if (!identical(as.integer(status), 0L) || !isTRUE(payload$ok)) {
    stop(payload$error %||% paste(output, collapse = "\n"))
  }
  list(payload = payload, log = output)
}

probe_source <- function(project_dir, source_path) {
  run_bridge(project_dir, c("probe", source_path))$payload
}

extract_source_frame <- function(
  project_dir,
  source_path,
  output_path,
  frame_index,
  rotation,
  flip_horizontal
) {
  args <- c(
    "frame", source_path, output_path,
    "--frame-index", as.integer(frame_index),
    "--rotation", as.integer(rotation)
  )
  if (isTRUE(flip_horizontal)) args <- c(args, "--flip-horizontal")
  run_bridge(project_dir, args)$payload
}

run_tracking_bridge <- function(project_dir, config) {
  args <- c(
    "run", config$source_path, config$output_dir,
    "--export-name", config$export_name,
    "--rotation", config$rotation,
    "--roi-x", config$roi_x,
    "--roi-y", config$roi_y,
    "--roi-width", config$roi_width,
    "--roi-height", config$roi_height,
    "--num-points", config$num_points,
    "--min-spacing", config$min_spacing,
    "--search-radius", config$search_radius,
    "--patch-size", config$patch_size,
    "--min-confidence", config$min_confidence,
    "--lookahead-frames", config$lookahead_frames,
    "--microns-per-pixel", config$microns_per_pixel,
    "--seconds-per-frame", config$seconds_per_frame,
    "--preview-fps", config$preview_fps,
    "--tracking-method", config$tracking_method
  )
  if (isTRUE(config$flip_horizontal)) args <- c(args, "--flip-horizontal")
  run_bridge(project_dir, args)
}

read_tracking_json <- function(path, project_dir) {
  data <- tryCatch(
    jsonlite::fromJSON(path, simplifyVector = FALSE),
    error = function(...) NULL
  )
  if (is.null(data)) return(NULL)
  outputs <- data$outputs %||% list()
  context <- data$run_context %||% list()
  source_path <- context$source_path %||% data$source_path %||% ""
  track_preview_mp4 <- resolve_result_path(
    project_dir,
    outputs$track_preview_mp4 %||% data$track_preview_video
  )
  inferred_webm <- if (nzchar(track_preview_mp4)) {
    sub("\\.mp4$", ".webm", track_preview_mp4, ignore.case = TRUE)
  } else ""
  data.frame(
    result_id = normalizePath(path, mustWork = FALSE),
    sample_id = as.character(data$sample_id %||% tools::file_path_sans_ext(basename(path))),
    source_name = basename(source_path),
    source_path = source_path,
    group = infer_group_from_path(project_dir, source_path),
    analyzed_at = as.character(data$analysis_timestamp_utc %||% context$created_at_utc %||% ""),
    absolute_velocity = safe_numeric(data$absolute_velocity_index_um_per_s %||% data$general_movement_index_um_per_s),
    downward_velocity = safe_numeric(data$downward_velocity_index_um_per_s),
    tracks_started = safe_numeric(data$num_tracks_started),
    valid_tracks = safe_numeric(data$num_tracks_with_valid_steps),
    valid_steps = safe_numeric(data$total_valid_steps),
    frame_count = safe_numeric(data$frame_count),
    trajectory_csv = resolve_result_path(project_dir, outputs$trajectory_csv %||% data$trajectory_csv),
    summary_json = normalizePath(path, mustWork = FALSE),
    starting_points = resolve_result_path(project_dir, outputs$starting_points_png %||% data$start_points_preview),
    track_overlay = resolve_result_path(project_dir, outputs$track_overlay_png %||% data$tracks_overlay_preview),
    track_preview = track_preview_mp4,
    track_preview_webm = resolve_result_path(
      project_dir,
      outputs$track_preview_webm %||% data$track_preview_webm %||% inferred_webm
    ),
    track_preview_mp4_codec = as.character(outputs$track_preview_mp4_codec %||% ""),
    track_preview_webm_codec = as.character(outputs$track_preview_webm_codec %||% ""),
    output_dir = as.character(data$output_dir %||% dirname(path)),
    tracking_method = as.character((data$parameters %||% list())$tracking_method %||% "unknown"),
    seconds_per_frame = safe_numeric((data$parameters %||% list())$seconds_per_frame),
    microns_per_pixel = safe_numeric((data$parameters %||% list())$microns_per_pixel),
    stringsAsFactors = FALSE
  )
}

discover_tracking_results <- function(project_dir) {
  project_dir <- normalize_project_path(project_dir)
  processed <- file.path(project_dir, "processed")
  if (!dir.exists(processed)) return(data.frame())
  paths <- list.files(
    processed,
    pattern = "_motion_index\\.json$",
    recursive = TRUE,
    full.names = TRUE,
    ignore.case = TRUE
  )
  if (length(paths) == 0) return(data.frame())
  rows <- lapply(paths, read_tracking_json, project_dir = project_dir)
  rows <- rows[!vapply(rows, is.null, logical(1))]
  if (length(rows) == 0) return(data.frame())
  result <- do.call(rbind, rows)
  result <- result[order(result$analyzed_at, decreasing = TRUE), , drop = FALSE]
  rownames(result) <- NULL
  result
}

result_choices <- function(results) {
  if (is.null(results) || nrow(results) == 0) return(character())
  label <- paste(results$group, results$source_name, results$analyzed_at, sep = "  /  ")
  stats::setNames(results$result_id, label)
}

angle_result_choices <- function(results) {
  if (is.null(results) || nrow(results) == 0) return(character())
  source <- ifelse(nzchar(results$source_name), results$source_name, "Unnamed source")
  method <- ifelse(
    results$tracking_method == "brightest_local",
    "Brightest points",
    ifelse(results$tracking_method == "template", "Template", results$tracking_method)
  )
  analyzed <- gsub("T", " ", substr(results$analyzed_at, 1, 19), fixed = TRUE)
  labels <- paste(source, results$group, method, analyzed, sep = "  •  ")
  stats::setNames(results$result_id, labels)
}

selected_row <- function(df, id, key) {
  if (is.null(df) || nrow(df) == 0 || is.null(id) || !nzchar(id)) return(NULL)
  rows <- df[df[[key]] == id, , drop = FALSE]
  if (nrow(rows) == 0) NULL else rows[1, , drop = FALSE]
}

read_trajectory <- function(path) {
  if (is.null(path) || !nzchar(path) || !file.exists(path)) return(data.frame())
  read.csv(path, stringsAsFactors = FALSE, check.names = FALSE)
}

wrap_angle_change <- function(angle_deg) {
  ((angle_deg + 180) %% 360) - 180
}

derive_angle_dynamics <- function(trajectory, seconds_per_frame = 1) {
  if (is.null(trajectory) || nrow(trajectory) == 0) return(data.frame())
  required <- c("track_id", "frame_index", "x_px", "y_px")
  if (!all(required %in% names(trajectory))) return(data.frame())

  data <- trajectory
  data$track_id <- as.character(data$track_id)
  data$frame_index <- safe_numeric(data$frame_index)
  data$x_px <- safe_numeric(data$x_px)
  data$y_px <- safe_numeric(data$y_px)
  data$motion_angle_deg <- NA_real_
  data$turning_angle_deg <- NA_real_
  data$elapsed_time_s <- data$frame_index * safe_numeric(seconds_per_frame %||% 1)

  groups <- split(seq_len(nrow(data)), data$track_id)
  for (indices in groups) {
    indices <- indices[order(data$frame_index[indices])]
    x <- data$x_px[indices]
    y <- data$y_px[indices]
    dx <- c(NA_real_, diff(x))
    dy <- c(NA_real_, diff(y))
    angle <- atan2(dy, dx) * 180 / pi
    angle[is.na(dx) | is.na(dy) | sqrt(dx ^ 2 + dy ^ 2) <= .Machine$double.eps] <- NA_real_

    turning <- rep(NA_real_, length(angle))
    valid <- which(!is.na(angle))
    if (length(valid) >= 2) {
      turning[valid[-1]] <- wrap_angle_change(diff(angle[valid]))
    }
    data$motion_angle_deg[indices] <- angle
    data$turning_angle_deg[indices] <- turning
  }

  data[order(data$track_id, data$frame_index), , drop = FALSE]
}

summarize_angle_dynamics <- function(angle_data) {
  empty <- list(
    circular_mean_deg = NA_real_, directional_stability = NA_real_,
    mean_absolute_turn_deg = NA_real_, reversal_count = 0L,
    pattern = "No motion", detail = "No valid consecutive motion steps."
  )
  if (is.null(angle_data) || nrow(angle_data) == 0) return(empty)
  angles <- safe_numeric(angle_data$motion_angle_deg)
  angles <- angles[!is.na(angles)]
  if (length(angles) == 0) return(empty)

  radians <- angles * pi / 180
  mean_sin <- mean(sin(radians))
  mean_cos <- mean(cos(radians))
  circular_mean <- atan2(mean_sin, mean_cos) * 180 / pi
  stability <- sqrt(mean_sin ^ 2 + mean_cos ^ 2)
  turns <- safe_numeric(angle_data$turning_angle_deg)
  turns <- turns[!is.na(turns)]
  mean_absolute_turn <- if (length(turns) > 0) mean(abs(turns)) else NA_real_
  reversals <- sum(abs(turns) >= 135, na.rm = TRUE)
  significant <- turns[abs(turns) >= 10]
  sign_changes <- if (length(significant) >= 2) {
    sum(sign(significant[-1]) != sign(significant[-length(significant)]))
  } else 0L
  oscillation_ratio <- if (length(significant) >= 2) sign_changes / (length(significant) - 1) else 0
  net_turn <- if (length(turns) > 0) sum(turns) else 0
  total_turn <- if (length(turns) > 0) sum(abs(turns)) else 0

  if (reversals > 0) {
    pattern <- "Reversing"
    detail <- "At least one step changes direction by 135° or more."
  } else if (stability >= 0.90 && (is.na(mean_absolute_turn) || mean_absolute_turn <= 15)) {
    pattern <- "Stable"
    detail <- "Step directions remain tightly concentrated."
  } else if (length(significant) >= 3 && oscillation_ratio >= 0.50 && abs(net_turn) < 0.50 * total_turn) {
    pattern <- "Oscillating"
    detail <- "Turning repeatedly alternates between clockwise and counterclockwise."
  } else if (abs(net_turn) >= 45) {
    pattern <- "Drifting"
    detail <- "Direction accumulates at least 45° of net turning."
  } else {
    pattern <- "Variable"
    detail <- "Direction varies without a dominant stable, drifting, oscillating, or reversing pattern."
  }

  list(
    circular_mean_deg = circular_mean,
    directional_stability = stability,
    mean_absolute_turn_deg = mean_absolute_turn,
    reversal_count = as.integer(reversals),
    pattern = pattern,
    detail = detail
  )
}

summarize_groups <- function(results) {
  if (is.null(results) || nrow(results) == 0) return(data.frame())
  groups <- split(results, results$group)
  rows <- lapply(names(groups), function(group_name) {
    group_df <- groups[[group_name]]
    data.frame(
      group = group_name,
      samples = nrow(group_df),
      mean_absolute_velocity = safe_mean(group_df$absolute_velocity),
      mean_downward_velocity = safe_mean(group_df$downward_velocity),
      total_valid_tracks = sum(group_df$valid_tracks, na.rm = TRUE),
      total_valid_steps = sum(group_df$valid_steps, na.rm = TRUE),
      stringsAsFactors = FALSE
    )
  })
  do.call(rbind, rows)
}

safe_output_file <- function(path) {
  is.character(path) && length(path) == 1 && nzchar(path) && file.exists(path)
}
