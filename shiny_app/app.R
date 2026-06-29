required_packages <- c(
  "shiny", "bslib", "ggplot2", "jsonlite", "png", "base64enc",
  "htmltools", "fontawesome"
)
missing_packages <- required_packages[!vapply(
  required_packages,
  requireNamespace,
  logical(1),
  quietly = TRUE
)]
if (length(missing_packages) > 0) {
  stop("Missing R packages: ", paste(missing_packages, collapse = ", "))
}

library(shiny)
library(bslib)
library(ggplot2)

locate_app_dir <- function() {
  candidates <- c(getwd(), file.path(getwd(), "shiny_app"))
  matches <- candidates[file.exists(file.path(candidates, "app.R"))]
  if (length(matches) == 0) stop("Could not locate the shiny_app directory.")
  normalizePath(matches[[1]], mustWork = TRUE)
}

APP_DIR <- locate_app_dir()
DEFAULT_PROJECT_DIR <- normalizePath(file.path(APP_DIR, ".."), mustWork = FALSE)
source(file.path(APP_DIR, "R", "helpers.R"), local = TRUE)

app_theme <- bs_theme(
  version = 5,
  bg = "#F3F5F6",
  fg = "#17211F",
  primary = "#147A6C",
  secondary = "#5D6866",
  success = "#2F7A4B",
  info = "#2E668E",
  warning = "#A66A16",
  danger = "#B33A3A",
  base_font = font_collection(
    "Inter",
    "Avenir Next",
    "Segoe UI",
    "Helvetica Neue",
    "Arial",
    "sans-serif"
  ),
  heading_font = font_collection(
    "Inter",
    "Avenir Next",
    "Segoe UI",
    "Helvetica Neue",
    "Arial",
    "sans-serif"
  ),
  border_radius = "6px"
)

page_heading <- function(kicker, title, description, actions = NULL) {
  div(
    class = "page-heading",
    div(
      class = "page-heading-copy",
      div(class = "page-kicker", kicker),
      h1(title),
      p(description)
    ),
    if (!is.null(actions)) div(class = "page-heading-actions", actions)
  )
}

empty_state <- function(icon_name, title, detail) {
  div(
    class = "empty-state",
    fontawesome::fa(icon_name, height = "24px"),
    h4(title),
    p(detail)
  )
}

status_pill <- function(text, tone = "neutral") {
  span(class = paste("status-pill", paste0("status-", tone)), text)
}

metric_value_box <- function(title, value, detail, icon_name, theme = "teal") {
  value_box(
    title = title,
    value = value,
    showcase = fontawesome::fa(icon_name, height = "22px"),
    p(class = "metric-detail", detail),
    class = paste("metric-box", paste0("metric-", theme))
  )
}

workflow_nav_choice <- function(step, icon_name, title, detail) {
  div(
    class = "workflow-nav-item",
    span(class = "workflow-step", step),
    div(
      class = "workflow-nav-copy",
      div(class = "workflow-nav-title", fontawesome::fa(icon_name, height = "14px"), span(title)),
      tags$small(detail)
    )
  )
}

navigation_choices <- list(
  workflow_nav_choice("1", "house", "Project", "Workspace, files, and preview"),
  workflow_nav_choice("2", "crosshairs", "Track", "Set ROI and run analysis"),
  workflow_nav_choice("3", "chart-line", "Review", "QC, motion, and angles"),
  workflow_nav_choice("4", "chart-column", "Compare", "Summarize by group")
)

reference_navigation <- workflow_nav_choice("·", "layer-group", "Z-stacks", "Microscopy file inventory")

all_navigation_choices <- c(navigation_choices, list(reference_navigation))
all_section_values <- c("project", "track", "review", "compare", "library")

section_legacy_map <- c(
  workspace = "project",
  tracking = "track",
  results = "review",
  angles = "review",
  analysis = "compare",
  stacks = "library"
)

normalize_section <- function(section) {
  if (!nzchar(section)) return("")
  mapped <- section_legacy_map[[section]]
  if (!is.null(mapped)) mapped else section
}

ui <- page_sidebar(
  title = div(
    class = "topbar-brand",
    span(class = "brand-mark", "AT"),
    div(
      strong("ActinTrackCV"),
      tags$small("F-actin motion analysis")
    )
  ),
  theme = app_theme,
  fillable = TRUE,
  sidebar = sidebar(
    width = 268,
    open = "desktop",
    id = "app_sidebar",
    class = "app-sidebar",
    div(
      class = "sidebar-section sidebar-context",
      div(class = "sidebar-label", "SESSION"),
      uiOutput("sidebar_workspace_chip"),
      uiOutput("sidebar_active_source")
    ),
    div(
      class = "sidebar-section app-navigation",
      div(class = "sidebar-label", "YOUR WORKFLOW"),
      radioButtons(
        "section",
        NULL,
        choiceNames = all_navigation_choices,
        choiceValues = all_section_values,
        selected = "project"
      )
    ),
    div(
      class = "sidebar-footer",
      uiOutput("sidebar_footer")
    )
  ),
  tags$head(
    tags$link(rel = "stylesheet", type = "text/css", href = "app.css")
  ),
  navset_hidden(
    id = "main_nav",
    nav_panel(
      title = "Project",
      value = "project",
      div(
        class = "app-view",
        page_heading(
          "STEP 1 · PROJECT",
          "Choose workspace and video",
          "Open your ActinTrackCV project folder, pick one video from that workspace, and confirm the live preview before tracking.",
          div(
            class = "page-heading-actions",
            input_task_button(
              "go_review",
              "Review results",
              icon = fontawesome::fa("chart-line"),
              class = "btn-outline-secondary"
            ),
            input_task_button(
              "go_tracking",
              "Track active video",
              icon = fontawesome::fa("crosshairs"),
              class = "btn-primary"
            )
          )
        ),
        card(
          class = "surface-card source-studio-card",
          card_header(
            div(
              strong("Source studio"),
              span(class = "card-subtitle", "Workspace-scoped file browser with live preview")
            )
          ),
          card_body(
            div(
              class = "workspace-bar",
              div(
                class = "workspace-bar-main",
                tags$label(`for` = "project_dir", class = "workspace-bar-label", "Project workspace"),
                textInput(
                  "project_dir",
                  NULL,
                  value = DEFAULT_PROJECT_DIR,
                  placeholder = "/path/to/ActinTrackCV"
                )
              ),
              div(
                class = "workspace-bar-actions",
                actionButton(
                  "apply_workspace",
                  "Open workspace",
                  icon = fontawesome::fa("folder-open"),
                  class = "btn-primary"
                ),
                actionButton(
                  "refresh_workspace",
                  "Refresh",
                  icon = fontawesome::fa("rotate"),
                  class = "btn-outline-secondary"
                )
              ),
              uiOutput("workspace_status")
            ),
            layout_columns(
              col_widths = c(4, 8),
              div(
                class = "source-browser-panel",
                div(
                  class = "source-browser-header",
                  strong("Videos in this workspace"),
                  uiOutput("source_browser_count")
                ),
                uiOutput("source_browser")
              ),
              div(
                class = "source-preview-panel",
                uiOutput("active_source_banner"),
                uiOutput("source_preview_controls"),
                plotOutput("source_preview_plot", height = "420px"),
                uiOutput("source_preview_status")
              )
            )
          )
        ),
        uiOutput("overview_metrics"),
        layout_columns(
          col_widths = c(7, 5),
          card(
            class = "surface-card",
            card_header(
              div(
                strong("Recent tracking runs"),
                span(class = "card-subtitle", "Newest validated outputs first")
              )
            ),
            card_body(uiOutput("recent_results"))
          ),
          card(
            class = "surface-card status-card",
            card_header(strong("Project readiness")),
            card_body(uiOutput("readiness_panel"))
          )
        )
      )
    ),
    nav_panel(
      title = "Track",
      value = "track",
      div(
        class = "app-view",
        page_heading(
          "STEP 2 · TRACK",
          "Configure and run tracking",
          "The active video from Project is used here. Set ROI on the preview frame, then run the tracker.",
          div(
            class = "page-heading-actions",
            actionButton(
              "go_project",
              "Change video",
              icon = fontawesome::fa("folder-open"),
              class = "btn-outline-secondary"
            ),
            actionButton(
              "refresh_preview",
              "Reload frame",
              icon = fontawesome::fa("rotate"),
              class = "btn-outline-secondary"
            )
          )
        ),
        uiOutput("tracking_source_banner"),
        layout_columns(
          col_widths = c(4, 8),
          card(
            class = "surface-card control-card",
            card_header(strong("Tracking setup")),
            card_body(
              div(
                class = "control-section",
                h5("Frame and orientation"),
                radioButtons(
                  "rotation",
                  "Rotation",
                  choices = c("0°" = 0, "90°" = 90, "180°" = 180, "270°" = 270),
                  selected = 0,
                  inline = TRUE
                ),
                checkboxInput("flip_horizontal", "Mirror horizontally", FALSE),
                uiOutput("frame_control")
              ),
              div(
                class = "control-section",
                div(
                  class = "control-heading-row",
                  h5("Region of interest"),
                  actionLink("use_full_frame", "Use full frame")
                ),
                p(class = "control-note", "Drag over the image or enter pixel bounds."),
                div(
                  class = "numeric-grid",
                  numericInput("roi_x", "X", 0, min = 0, step = 1),
                  numericInput("roi_y", "Y", 0, min = 0, step = 1),
                  numericInput("roi_width", "Width", 0, min = 1, step = 1),
                  numericInput("roi_height", "Height", 0, min = 1, step = 1)
                )
              ),
              div(
                class = "control-section",
                h5("Point matching"),
                radioButtons(
                  "tracking_method",
                  "Tracking method",
                  choiceNames = c(
                    "Brightest nearby points (Dr. Ju method)",
                    "Template matching"
                  ),
                  choiceValues = c("brightest_local", "template"),
                  selected = "brightest_local"
                ),
                div(
                  class = "control-note tracking-method-note",
                  uiOutput("tracking_method_help")
                ),
                div(
                  class = "numeric-grid",
                  numericInput("num_points", "Starting points", 10, min = 1, max = 50),
                  numericInput("min_spacing", "Min point spacing (px)", 20, min = 1, max = 200),
                  numericInput("search_radius", "Search radius (px)", 8, min = 1, max = 100),
                  numericInput("min_confidence", "Min match confidence", 0.55, min = 0, max = 1, step = 0.05),
                  numericInput("patch_size", "Patch size (px, odd)", 11, min = 3, max = 101, step = 2)
                )
              ),
              div(
                class = "control-section",
                h5("Calibration"),
                div(
                  class = "numeric-grid two-column",
                  numericInput("microns_per_pixel", "Microns / pixel", 0.265, min = 0.001, step = 0.001),
                  numericInput("seconds_per_frame", "Seconds / frame", 30, min = 0.001, step = 1)
                ),
                div(class = "calibration-warning", fontawesome::fa("triangle-exclamation"), " Confirm these values from acquisition metadata.")
              ),
              tags$details(
                class = "advanced-settings",
                tags$summary("Advanced matching settings"),
                div(
                  class = "numeric-grid",
                  numericInput("lookahead_frames", "Lookahead frames", 0, min = 0, max = 3),
                  numericInput("preview_fps", "QC video FPS", 5, min = 1, max = 30),
                  div()
                )
              ),
              input_task_button(
                "run_tracking",
                "Run calibrated tracking",
                icon = fontawesome::fa("play"),
                class = "btn-run"
              )
            )
          ),
          card(
            class = "surface-card preview-card",
            card_header(
              div(
                strong("ROI preview"),
                uiOutput("preview_status")
              )
            ),
            card_body(
              plotOutput(
                "frame_plot",
                height = "620px",
                brush = brushOpts(
                  id = "roi_brush",
                  fill = "#FFD166",
                  stroke = "#F3B61F",
                  opacity = 0.18,
                  resetOnNew = TRUE
                )
              ),
              div(class = "preview-footer", uiOutput("roi_summary"))
            )
          )
        ),
        card(
          class = "surface-card run-log-card",
          card_header(strong("Run activity")),
          card_body(uiOutput("run_activity"))
        )
      )
    ),
    nav_panel(
      title = "Review",
      value = "review",
      div(
        class = "app-view",
        page_heading(
          "STEP 3 · REVIEW",
          "Inspect a completed run",
          "Choose a tracking result, then explore QC imagery, motion metrics, and angle dynamics.",
          uiOutput("result_selector")
        ),
        uiOutput("review_context_banner"),
        uiOutput("review_method_note"),
        navset_tab(
          id = "review_tab",
          nav_panel(
            "Overview",
            uiOutput("result_metrics"),
            layout_columns(
              col_widths = c(6, 6),
              card(
                class = "surface-card media-card",
                card_header(strong("Starting points")),
                card_body(uiOutput("starting_points_media"))
              ),
              card(
                class = "surface-card media-card",
                card_header(strong("Track overlay")),
                card_body(uiOutput("track_overlay_media"))
              )
            ),
            card(
              class = "surface-card media-card",
              card_header(strong("Tracking preview video")),
              card_body(uiOutput("track_video"))
            )
          ),
          nav_panel(
            "Motion",
            layout_columns(
              col_widths = c(6, 6),
              card(
                class = "surface-card plot-card",
                card_header(strong("Track paths")),
                card_body(plotOutput("trajectory_plot", height = "350px"))
              ),
              card(
                class = "surface-card plot-card",
                card_header(strong("Absolute velocity by frame")),
                card_body(plotOutput("velocity_plot", height = "350px"))
              )
            ),
            card(
              class = "surface-card",
              card_header(
                div(
                  strong("Trajectory data"),
                  div(
                    class = "card-actions",
                    downloadButton("download_trajectory", "CSV", class = "btn-sm"),
                    downloadButton("download_summary", "JSON", class = "btn-sm")
                  )
                )
              ),
              card_body(uiOutput("trajectory_table"))
            )
          ),
          nav_panel(
            "Angles",
            div(
              class = "analysis-definition-note",
              fontawesome::fa("circle-info"),
              " Angle convention: 0° = right, +90° = down, ±180° = left, and -90° = up in image coordinates. Turning is wrapped to -180°…+180°."
            ),
            uiOutput("angle_metrics"),
            layout_columns(
              col_widths = c(7, 5),
              card(
                class = "surface-card media-card angle-preview-card",
                card_header(
                  div(
                    strong("Full-sequence tracking preview"),
                    span(class = "card-subtitle", "Confirms which source and tracks are being analyzed")
                  )
                ),
                card_body(uiOutput("angle_preview_media"))
              ),
              card(
                class = "surface-card media-card angle-overlay-card",
                card_header(
                  div(
                    strong("Trajectory overlay"),
                    span(class = "card-subtitle", "All tracked paths for the selected run")
                  )
                ),
                card_body(uiOutput("angle_overlay_media"))
              )
            ),
            layout_columns(
              col_widths = c(6, 6),
              card(
                class = "surface-card plot-card",
                card_header(strong("Instantaneous motion angle")),
                card_body(plotOutput("motion_angle_plot", height = "360px"))
              ),
              card(
                class = "surface-card plot-card",
                card_header(strong("Turning angle between steps")),
                card_body(plotOutput("turning_angle_plot", height = "360px"))
              )
            ),
            card(
              class = "surface-card plot-card",
              card_header(strong("Tracked position through time")),
              card_body(plotOutput("position_time_plot", height = "330px"))
            ),
            card(
              class = "surface-card",
              card_header(
                div(
                  strong("Per-step angle data"),
                  downloadButton("download_angle_data", "CSV", class = "btn-sm")
                )
              ),
              card_body(uiOutput("angle_table"))
            )
          )
        )
      )
    ),
    nav_panel(
      title = "Compare",
      value = "compare",
      div(
        class = "app-view",
        page_heading(
          "STEP 4 · COMPARE",
          "Group-level movement",
          "Compare absolute and directional velocity across biological groups using completed runs.",
          actionButton("refresh_analysis", "Refresh", icon = fontawesome::fa("rotate"), class = "btn-outline-secondary")
        ),
        uiOutput("analysis_metrics"),
        layout_columns(
          col_widths = c(8, 4),
          card(
            class = "surface-card plot-card",
            card_header(strong("Mean velocity by group")),
            card_body(plotOutput("group_plot", height = "420px"))
          ),
          card(
            class = "surface-card",
            card_header(strong("Group summary")),
            card_body(uiOutput("group_table"))
          )
        ),
        card(
          class = "surface-card",
          card_header(strong("Completed runs")),
          card_body(uiOutput("all_results_table"))
        )
      )
    ),
    nav_panel(
      title = "Z-stacks",
      value = "library",
      div(
        class = "app-view",
        page_heading(
          "REFERENCE · Z-STACKS",
          "Microscopy file inventory",
          "Audit raw Olympus and TIFF stacks without mixing them into the current 2D velocity pipeline.",
          status_pill("Inventory only", "warning")
        ),
        uiOutput("stack_metrics"),
        layout_columns(
          col_widths = c(8, 4),
          card(
            class = "surface-card",
            card_header(strong("Microscopy files")),
            card_body(uiOutput("stack_table"))
          ),
          card(
            class = "surface-card",
            card_header(strong("Selected stack")),
            card_body(
              uiOutput("stack_selector"),
              uiOutput("stack_detail")
            )
          )
        ),
        card(
          class = "surface-card next-step-card",
          card_header(strong("Required before 3D analysis")),
          card_body(
            div(class = "step-list",
              div(span("1"), p("Extract dimensions, channels, pixel size, z-step, and bit depth.")),
              div(span("2"), p("Convert to OME-TIFF or another analysis-safe representation.")),
              div(span("3"), p("Generate max-projection and middle-slice QC previews.")),
              div(span("4"), p("Keep depth and thickness outputs separate from 2D velocity."))
            )
          )
        )
      )
    )
  )
)

server <- function(input, output, session) {
  refresh_token <- reactiveVal(0L)
  preview_state <- reactiveVal(NULL)
  preview_error <- reactiveVal("")
  source_probe <- reactiveVal(NULL)
  probe_error <- reactiveVal("")
  run_state <- reactiveVal(list(status = "idle", message = "No tracking run started in this session.", log = character()))
  pending_result <- reactiveVal("")
  requested_section <- reactiveVal("")
  applied_workspace <- reactiveVal(normalize_project_path(DEFAULT_PROJECT_DIR))
  active_source_path <- reactiveVal("")

  project_dir <- reactive(applied_workspace())

  observeEvent(session$clientData$url_search, {
    query <- parseQueryString(session$clientData$url_search)
    requested <- normalize_section(query$section %||% "")
    if (requested %in% all_section_values) {
      requested_section(requested)
      updateRadioButtons(session, "section", selected = requested)
      nav_select("main_nav", selected = requested)
    }
  }, once = TRUE)

  observeEvent(input$refresh_workspace, {
    active_source_path("")
    applied_workspace(normalize_project_path(input$project_dir %||% DEFAULT_PROJECT_DIR))
    refresh_token(refresh_token() + 1L)
    showNotification("Workspace refreshed", type = "message", duration = 2)
  })
  observeEvent(input$apply_workspace, {
    active_source_path("")
    applied_workspace(normalize_project_path(input$project_dir %||% DEFAULT_PROJECT_DIR))
    refresh_token(refresh_token() + 1L)
    showNotification("Workspace opened", type = "message", duration = 2)
  })
  observeEvent(input$refresh_analysis, refresh_token(refresh_token() + 1L))

  sources <- reactive({
    refresh_token()
    discover_video_sources(project_dir())
  })
  results <- reactive({
    refresh_token()
    discover_tracking_results(project_dir())
  })
  stacks <- reactive({
    refresh_token()
    discover_z_stacks(project_dir())
  })

  observeEvent(sources(), {
    data <- sources()
    next_path <- coerce_active_source_path(data, active_source_path())
    if (!identical(next_path, active_source_path())) {
      active_source_path(next_path)
    }
  }, ignoreInit = FALSE)

  observeEvent(input$source_file, {
    selected <- input$source_file %||% ""
    if (nzchar(selected) && !identical(selected, active_source_path())) {
      active_source_path(selected)
    }
  }, ignoreInit = FALSE)

  observeEvent(input$section, {
    target <- requested_section()
    if (!nzchar(target)) target <- input$section
    requested_section("")
    nav_select("main_nav", selected = target)
    if (identical(target, "track") && nzchar(active_source_path())) {
      load_preview_frame(
        as.integer(input$frame_index %||% 0),
        rotation = as.integer(input$rotation %||% 0),
        flip_horizontal = isTRUE(input$flip_horizontal)
      )
    }
  }, ignoreInit = FALSE)

  observeEvent(input$go_tracking, {
    if (!nzchar(active_source_path()) || is.null(selected_source())) {
      showNotification("Select a video in Project before tracking.", type = "warning", duration = 4)
      updateRadioButtons(session, "section", selected = "project")
      nav_select("main_nav", selected = "project")
      return()
    }
    updateRadioButtons(session, "section", selected = "track")
    nav_select("main_nav", selected = "track")
  })

  observeEvent(input$go_review, {
    updateRadioButtons(session, "section", selected = "review")
    nav_select("main_nav", selected = "review")
  })

  observeEvent(input$go_project, {
    updateRadioButtons(session, "section", selected = "project")
    nav_select("main_nav", selected = "project")
  })

  selected_source <- reactive({
    path <- active_source_path()
    if (!nzchar(path)) return(NULL)
    rows <- sources()[sources()$path == path, , drop = FALSE]
    if (nrow(rows) == 0) NULL else rows[1, , drop = FALSE]
  })

  load_preview_frame <- function(frame_index = 0L, rotation = NULL, flip_horizontal = NULL) {
    path <- active_source_path()
    req(nzchar(path))
    rotation <- as.integer(rotation %||% input$rotation %||% 0)
    flip_horizontal <- isTRUE(flip_horizontal %||% input$flip_horizontal)
    preview_error("")
    old_state <- preview_state()
    output_path <- tempfile("actintrack_frame_", fileext = ".png")
    tryCatch({
      metadata <- extract_source_frame(
        project_dir(),
        path,
        output_path,
        as.integer(frame_index),
        rotation,
        flip_horizontal
      )
      orientation_key <- paste(path, rotation, flip_horizontal)
      old_key <- old_state$orientation_key %||% ""
      preview_state(list(
        path = output_path,
        metadata = metadata,
        orientation_key = orientation_key
      ))
      if (!identical(orientation_key, old_key)) {
        updateNumericInput(session, "roi_x", value = 0, max = metadata$width)
        updateNumericInput(session, "roi_y", value = 0, max = metadata$height)
        updateNumericInput(session, "roi_width", value = metadata$width, max = metadata$width)
        updateNumericInput(session, "roi_height", value = metadata$height, max = metadata$height)
      }
    }, error = function(exc) {
      preview_error(conditionMessage(exc))
      preview_state(NULL)
    })
  }

  observeEvent(active_source_path(), {
    path <- active_source_path()
    if (!nzchar(path)) {
      source_probe(NULL)
      preview_state(NULL)
      probe_error("")
      preview_error("")
      return()
    }
    probe_error("")
    source_probe(NULL)
    tryCatch({
      metadata <- probe_source(project_dir(), path)
      source_probe(metadata)
      load_preview_frame(0L, rotation = 0, flip_horizontal = FALSE)
      updateSliderInput(session, "studio_frame_index", value = 0)
      updateSliderInput(session, "frame_index", value = 0)
    }, error = function(exc) {
      probe_error(conditionMessage(exc))
      preview_state(NULL)
    })
  }, ignoreInit = FALSE)

  workspace_info <- reactive(workspace_state(project_dir()))

  output$workspace_status <- renderUI({
    info <- workspace_info()
    pending <- normalize_project_path(input$project_dir %||% "")
    dirty <- !identical(pending, applied_workspace())
    div(
      class = "workspace-status-row",
      span(class = paste("status-dot", if (info$valid) "dot-ok" else "dot-error")),
      span(info$message),
      if (dirty) span(class = "workspace-pending-note", "Press Open workspace to apply path changes")
    )
  })

  output$sidebar_workspace_chip <- renderUI({
    info <- workspace_info()
    div(
      class = "sidebar-chip",
      fontawesome::fa("folder", height = "12px"),
      div(
        class = "sidebar-chip-copy",
        tags$small("WORKSPACE"),
        span(basename(info$path))
      )
    )
  })

  output$sidebar_active_source <- renderUI({
    row <- selected_source()
    div(
      class = "sidebar-chip",
      fontawesome::fa("film", height = "12px"),
      div(
        class = "sidebar-chip-copy",
        tags$small("ACTIVE VIDEO"),
        span(if (is.null(row)) "None selected" else row$file_name)
      )
    )
  })

  output$source_browser_count <- renderUI({
    count <- nrow(sources())
    span(class = "source-browser-count", paste0(count, " file", if (count == 1) "" else "s"))
  })

  output$source_browser <- renderUI({
    data <- sources()
    info <- workspace_info()
    if (!info$valid) {
      return(empty_state(
        "folder-open",
        "Workspace not found",
        "Enter a valid ActinTrackCV project folder, then click Open workspace."
      ))
    }
    if (nrow(data) == 0) {
      return(empty_state(
        "film",
        "No videos in this workspace",
        "Add AVI or MP4 files under raw/ or processed/, then refresh."
      ))
    }
    active <- active_source_path()
    if (!nzchar(active) || !active %in% data$path) {
      active <- coerce_active_source_path(data, active)
    }
    div(
      class = "source-browser",
      radioButtons(
        "source_file",
        NULL,
        choiceNames = lapply(seq_len(nrow(data)), function(i) {
          source_file_choice_label(data[i, , drop = FALSE], identical(data$path[[i]], active))
        }),
        choiceValues = data$path,
        selected = active
      )
    )
  })

  output$active_source_banner <- renderUI({
    active_source_banner(
      selected_source(),
      source_probe(),
      "Select a video from the workspace list to preview it here."
    )
  })

  output$source_preview_controls <- renderUI({
    row <- selected_source()
    metadata <- source_probe()
    if (is.null(row) || is.null(metadata)) return(NULL)
    sliderInput(
      "studio_frame_index",
      "Preview frame",
      min = 0,
      max = max(0, as.integer(metadata$frame_count) - 1),
      value = min(as.integer(input$studio_frame_index %||% 0), max(0, as.integer(metadata$frame_count) - 1)),
      step = 1,
      ticks = FALSE
    )
  })

  studio_preview_request <- reactive({
    path <- active_source_path()
    req(nzchar(path))
    list(
      path = path,
      frame = as.integer(input$studio_frame_index %||% 0)
    )
  })

  observeEvent(studio_preview_request(), {
    if (isolate(input$section) != "project") return()
    request <- studio_preview_request()
    if (!identical(request$path, active_source_path())) return()
    load_preview_frame(request$frame, rotation = 0, flip_horizontal = FALSE)
  }, ignoreInit = FALSE)

  render_preview_image <- function(show_roi = FALSE) {
    state <- preview_state()
    if (is.null(state) || !file.exists(state$path)) {
      par(mar = c(0, 0, 0, 0), bg = "#111817")
      plot.new()
      text(0.5, 0.54, "Select a video to preview", col = "#DCE4E2", cex = 1.2)
      text(0.5, 0.46, preview_error() %||% probe_error() %||% "A preview frame will appear here.", col = "#83918E", cex = 0.9)
      return()
    }
    image <- png::readPNG(state$path)
    image <- image[dim(image)[1]:1, , , drop = FALSE]
    width <- as.numeric(state$metadata$width)
    height <- as.numeric(state$metadata$height)
    par(mar = c(0, 0, 0, 0), bg = "#111817", xaxs = "i", yaxs = "i")
    plot.new()
    plot.window(xlim = c(0, width), ylim = c(0, height), asp = 1)
    rasterImage(image, 0, 0, width, height, interpolate = TRUE)
    if (show_roi) {
      x <- max(0, min(width, input$roi_x %||% 0))
      y <- max(0, min(height, input$roi_y %||% 0))
      roi_width <- max(1, min(width - x, input$roi_width %||% width))
      roi_height <- max(1, min(height - y, input$roi_height %||% height))
      rect(
        x,
        height - y - roi_height,
        x + roi_width,
        height - y,
        border = "#FFD166",
        lwd = 2
      )
    }
  }

  output$source_preview_plot <- renderPlot({
    render_preview_image(show_roi = FALSE)
  })

  output$source_preview_status <- renderUI({
    row <- selected_source()
    if (is.null(row)) return(NULL)
    if (nzchar(probe_error())) return(status_pill("Probe error", "danger"))
    if (nzchar(preview_error())) return(status_pill("Preview error", "danger"))
    if (is.null(preview_state())) return(status_pill("Loading preview", "neutral"))
    metadata <- source_probe()
    summary <- format_video_probe_summary(metadata)
    div(
      class = "source-preview-meta",
      span(paste0("Frame ", input$studio_frame_index %||% 0)),
      span(paste0(summary$playback_fps, " playback FPS")),
      span(summary$dimensions)
    )
  })

  output$source_sidebar_meta <- renderUI(NULL)

  output$sidebar_footer <- renderUI({
    status <- run_state()
    div(
      class = "session-status",
      div(
        tags$small("SESSION"),
        span(if (status$status == "running") "Tracking in progress" else if (status$status == "success") "Latest run complete" else "Ready")
      )
    )
  })

  output$overview_metrics <- renderUI({
    layout_columns(
      col_widths = c(3, 3, 3, 3),
      metric_value_box("Video sources", nrow(sources()), "AVI and MP4 files", "film", "teal"),
      metric_value_box("Tracking runs", nrow(results()), "Saved result sets", "route", "blue"),
      metric_value_box("Z-stacks", nrow(stacks()), "OIR, OIB, and TIFF", "layer-group", "amber"),
      metric_value_box(
        "Calibration",
        paste0(format_metric(input$seconds_per_frame, 0), " s"),
        paste0(format_metric(input$microns_per_pixel, 3), " µm / pixel"),
        "ruler-combined",
        "gray"
      )
    )
  })

  output$source_empty <- renderUI(NULL)
  output$source_table_inner <- renderTable(data.frame(), rownames = FALSE)

  output$recent_results <- renderUI({
    data <- results()
    if (nrow(data) == 0) return(empty_state("route", "No completed runs", "Configure an ROI and run tracking to create the first result."))
    div(class = "recent-run-list", lapply(seq_len(min(5, nrow(data))), function(i) {
      row <- data[i, , drop = FALSE]
      div(
        class = "recent-run",
        div(
          strong(row$source_name),
          tags$small(paste(row$group, row$analyzed_at, sep = " · "))
        ),
        div(
          class = "recent-run-metric",
          span(format_metric(row$absolute_velocity, 3)),
          tags$small("µm/s")
        )
      )
    }))
  })

  output$readiness_panel <- renderUI({
    checks <- list(
      list(ok = workspace_info()$valid, text = "Workspace folder exists"),
      list(ok = nrow(sources()) > 0, text = "Video sources discovered"),
      list(ok = nzchar(active_source_path()), text = "Active video selected"),
      list(ok = !is.null(source_probe()), text = "Active video probed successfully"),
      list(ok = nrow(results()) > 0, text = "At least one tracking result available"),
      list(ok = input$seconds_per_frame > 0, text = "Acquisition interval entered"),
      list(ok = input$microns_per_pixel > 0, text = "Pixel calibration entered")
    )
    div(class = "readiness-grid", lapply(checks, function(check) {
      div(
        class = "readiness-item",
        fontawesome::fa(if (check$ok) "circle-check" else "circle", height = "16px"),
        span(check$text)
      )
    }))
  })

  output$tracking_method_help <- renderUI({
    method <- input$tracking_method %||% "brightest_local"
    if (identical(method, "template")) {
      return(paste(
        "Matches a small image patch from the previous frame inside the search window.",
        "Use for comparison; Dr. Ju's recommended workflow is brightest nearby points."
      ))
    }
    paste(
      "In each frame, find the brightest nearby actin landmark within the search radius.",
      "This is the same method as the Python workbench default and Dr. Ju's traditional CV approach."
    )
  })

  output$frame_control <- renderUI({
    metadata <- source_probe()
    if (is.null(metadata)) return(NULL)
    sliderInput(
      "frame_index",
      "Preview frame",
      min = 0,
      max = max(0, as.integer(metadata$frame_count) - 1),
      value = 0,
      step = 1,
      ticks = FALSE
    )
  })

  preview_request <- reactive({
    path <- active_source_path()
    req(nzchar(path))
    list(
      source = path,
      frame = as.integer(input$frame_index %||% 0),
      rotation = as.integer(input$rotation %||% 0),
      flip = isTRUE(input$flip_horizontal),
      refresh = input$refresh_preview
    )
  })

  observeEvent(preview_request(), {
    if (isolate(input$section) != "track") return()
    request <- preview_request()
    load_preview_frame(request$frame, rotation = request$rotation, flip_horizontal = request$flip)
  }, ignoreInit = FALSE)

  observeEvent(input$use_full_frame, {
    state <- preview_state()
    req(state)
    updateNumericInput(session, "roi_x", value = 0)
    updateNumericInput(session, "roi_y", value = 0)
    updateNumericInput(session, "roi_width", value = state$metadata$width)
    updateNumericInput(session, "roi_height", value = state$metadata$height)
  })

  observeEvent(input$roi_brush, {
    brush <- input$roi_brush
    state <- preview_state()
    req(brush, state)
    width <- as.integer(state$metadata$width)
    height <- as.integer(state$metadata$height)
    x0 <- max(0, floor(min(brush$xmin, brush$xmax)))
    x1 <- min(width, ceiling(max(brush$xmin, brush$xmax)))
    display_y0 <- max(0, floor(min(brush$ymin, brush$ymax)))
    display_y1 <- min(height, ceiling(max(brush$ymin, brush$ymax)))
    image_y0 <- max(0, height - display_y1)
    updateNumericInput(session, "roi_x", value = x0)
    updateNumericInput(session, "roi_y", value = image_y0)
    updateNumericInput(session, "roi_width", value = max(1, x1 - x0))
    updateNumericInput(session, "roi_height", value = max(1, display_y1 - display_y0))
  })

  output$frame_plot <- renderPlot({
    render_preview_image(show_roi = TRUE)
  })

  output$preview_status <- renderUI({
    if (nzchar(preview_error())) return(status_pill("Preview error", "danger"))
    if (is.null(preview_state())) return(status_pill("Waiting for source", "neutral"))
    status_pill(paste0("Frame ", input$frame_index %||% 0), "success")
  })

  output$tracking_source_banner <- renderUI({
    if (is.null(selected_source())) {
      return(active_source_banner(NULL, NULL, "Go to Project, open a workspace, and select a video."))
    }
    active_source_banner(selected_source(), source_probe())
  })

  output$roi_summary <- renderUI({
    state <- preview_state()
    if (is.null(state)) return(span("No ROI available"))
    area <- as.numeric(input$roi_width %||% 0) * as.numeric(input$roi_height %||% 0)
    coverage <- 100 * area / (as.numeric(state$metadata$width) * as.numeric(state$metadata$height))
    div(
      span(fontawesome::fa("crop-simple"), paste0(input$roi_width, " × ", input$roi_height, " px")),
      span(paste0(format_metric(coverage, 1), "% of frame")),
      span(paste0("Origin ", input$roi_x, ", ", input$roi_y))
    )
  })

  observeEvent(input$run_tracking, {
    row <- selected_source()
    state <- preview_state()
    req(row, state)
    if (input$patch_size %% 2 == 0) {
      showNotification("Patch size must be an odd number.", type = "error")
      return()
    }
    if (input$roi_width < 3 || input$roi_height < 3) {
      showNotification("Draw a larger ROI before running tracking.", type = "error")
      return()
    }
    timestamp <- format(Sys.time(), "%Y%m%d_%H%M%S")
    export_name <- paste0(tools::file_path_sans_ext(row$file_name), "_", timestamp)
    output_dir <- file.path(
      project_dir(),
      "processed",
      "shiny_runs",
      row$group,
      tools::file_path_sans_ext(row$file_name),
      timestamp
    )
    config <- list(
      source_path = row$path,
      output_dir = output_dir,
      export_name = export_name,
      rotation = as.integer(input$rotation),
      flip_horizontal = isTRUE(input$flip_horizontal),
      roi_x = as.integer(input$roi_x),
      roi_y = as.integer(input$roi_y),
      roi_width = as.integer(input$roi_width),
      roi_height = as.integer(input$roi_height),
      num_points = as.integer(input$num_points),
      min_spacing = as.integer(input$min_spacing),
      search_radius = as.integer(input$search_radius),
      patch_size = as.integer(input$patch_size),
      min_confidence = as.numeric(input$min_confidence),
      lookahead_frames = as.integer(input$lookahead_frames),
      microns_per_pixel = as.numeric(input$microns_per_pixel),
      seconds_per_frame = as.numeric(input$seconds_per_frame),
      preview_fps = as.numeric(input$preview_fps),
      tracking_method = input$tracking_method
    )
    run_state(list(status = "running", message = paste("Tracking", row$file_name), log = character()))
    tryCatch({
      bridge_result <- withProgress(
        message = "Running calibrated tracking",
        detail = "Cropping lossless frames and following bright actin landmarks...",
        value = 0.55,
        run_tracking_bridge(project_dir(), config)
      )
      summary_path <- bridge_result$payload$outputs$summary_json %||% ""
      pending_result(summary_path)
      run_state(list(
        status = "success",
        message = paste("Completed", row$file_name),
        log = bridge_result$log,
        payload = bridge_result$payload
      ))
      refresh_token(refresh_token() + 1L)
      updateRadioButtons(session, "section", selected = "review")
      nav_select("main_nav", selected = "review")
      showNotification("Tracking run completed", type = "message", duration = 4)
    }, error = function(exc) {
      run_state(list(status = "error", message = conditionMessage(exc), log = character()))
      showNotification(conditionMessage(exc), type = "error", duration = 10)
    })
  })

  output$run_activity <- renderUI({
    state <- run_state()
    icon_name <- if (state$status == "success") "circle-check" else if (state$status == "error") "circle-exclamation" else if (state$status == "running") "spinner" else "clock"
    div(
      class = paste("run-activity", paste0("run-", state$status)),
      fontawesome::fa(icon_name),
      div(
        strong(state$message),
        if (length(state$log) > 0) tags$details(tags$summary("Show technical log"), tags$pre(paste(state$log, collapse = "\n")))
      )
    )
  })

  observeEvent(results(), {
    choices <- angle_result_choices(results())
    selected <- pending_result()
    if (!nzchar(selected) || !selected %in% unname(choices)) selected <- input$result_file
    if (length(choices) > 0 && (is.null(selected) || !selected %in% unname(choices))) selected <- unname(choices[[1]])
    updateSelectInput(session, "result_file", choices = choices, selected = selected)
  }, ignoreInit = FALSE)

  output$result_selector <- renderUI({
    div(
      class = "result-selector-wrap",
      selectInput("result_file", "Tracking result", choices = angle_result_choices(results()), width = "420px"),
      div(class = "selector-help", "Each option shows source, group, tracker, and run time.")
    )
  })

  selected_result <- reactive(selected_row(results(), input$result_file %||% "", "result_id"))
  trajectory <- reactive({
    row <- selected_result()
    if (is.null(row)) return(data.frame())
    read_trajectory(row$trajectory_csv)
  })
  angle_trajectory <- reactive({
    row <- selected_result()
    if (is.null(row)) return(data.frame())
    derive_angle_dynamics(
      read_trajectory(row$trajectory_csv),
      row$seconds_per_frame %||% 1
    )
  })
  angle_summary <- reactive(summarize_angle_dynamics(angle_trajectory()))

  output$review_context_banner <- renderUI({
    row <- selected_result()
    if (is.null(row)) {
      return(empty_state("file-circle-question", "No tracking result selected", "Choose a completed run above to preview and analyze it."))
    }
    relative_source <- relative_to_project(project_dir(), row$source_path)
    method_label <- if (identical(row$tracking_method, "brightest_local")) {
      "Brightest nearby points"
    } else if (identical(row$tracking_method, "template")) {
      "Template matching"
    } else {
      row$tracking_method
    }
    div(
      class = "selected-file-banner",
      div(class = "selected-file-icon", fontawesome::fa("file-video")),
      div(
        class = "selected-file-copy",
        div(class = "selected-file-label", "SELECTED RUN"),
        strong(row$source_name),
        p(relative_source)
      ),
      div(
        class = "selected-file-tags",
        status_pill(row$group, "info"),
        status_pill(method_label, "neutral"),
        span(class = "selected-file-time", paste("Run", gsub("T", " ", substr(row$analyzed_at, 1, 19), fixed = TRUE)))
      )
    )
  })

  output$review_method_note <- renderUI({
    row <- selected_result()
    if (is.null(row)) return(NULL)
    method_label <- if (identical(row$tracking_method, "brightest_local")) {
      "Brightest nearby points"
    } else if (identical(row$tracking_method, "template")) {
      "Template matching"
    } else {
      row$tracking_method
    }
    div(
      class = "analysis-definition-note review-method-note",
      fontawesome::fa("circle-info"),
      " Review shows the saved tracking run. Method: ",
      strong(method_label),
      ". Compare the track overlay and preview video — if points jump or swap identity, re-run on Track with brightest nearby points, a tighter ROI, and settings matching the Python app."
    )
  })

  output$result_metrics <- renderUI({
    row <- selected_result()
    if (is.null(row)) return(empty_state("route", "No result selected", "Run tracking or choose a saved result."))
    layout_columns(
      col_widths = c(3, 3, 3, 3),
      metric_value_box("Absolute velocity", paste0(format_metric(row$absolute_velocity), " µm/s"), "Primary movement metric", "arrows-up-down-left-right", "teal"),
      metric_value_box("Downward velocity", paste0(format_metric(row$downward_velocity), " µm/s"), "Directional secondary metric", "arrow-down", "blue"),
      metric_value_box("Valid tracks", format_metric(row$valid_tracks, 0), paste0(format_metric(row$tracks_started, 0), " started"), "route", "amber"),
      metric_value_box("Valid steps", format_metric(row$valid_steps, 0), paste0(format_metric(row$frame_count, 0), " frames"), "list-check", "gray")
    )
  })

  plot_theme <- function() {
    theme_minimal(base_size = 12) +
      theme(
        plot.background = element_rect(fill = "transparent", color = NA),
        panel.background = element_rect(fill = "transparent", color = NA),
        panel.grid.minor = element_blank(),
        panel.grid.major = element_line(color = "#E3E8E6", linewidth = 0.4),
        axis.title = element_text(color = "#52605D"),
        axis.text = element_text(color = "#687572"),
        legend.position = "bottom",
        legend.title = element_blank()
      )
  }

  output$trajectory_plot <- renderPlot({
    data <- trajectory()
    validate(need(nrow(data) > 0, "No trajectory data for this result."))
    data$track_id <- factor(data$track_id)
    ggplot(data, aes(x = x_px, y = y_px, group = track_id, color = track_id)) +
      geom_path(linewidth = 0.8, alpha = 0.8) +
      geom_point(size = 1.6) +
      scale_y_reverse() +
      coord_equal() +
      labs(x = "X position (px)", y = "Y position (px)") +
      plot_theme()
  })

  output$velocity_plot <- renderPlot({
    data <- trajectory()
    validate(need(nrow(data) > 0, "No trajectory data for this result."))
    validate(need("absolute_velocity_um_per_s" %in% names(data), "Run output does not contain per-step velocity."))
    data <- data[!is.na(data$absolute_velocity_um_per_s), , drop = FALSE]
    data$track_id <- factor(data$track_id)
    ggplot(data, aes(x = frame_index, y = absolute_velocity_um_per_s, group = track_id, color = track_id)) +
      geom_line(linewidth = 0.7, alpha = 0.75) +
      geom_point(size = 1.4) +
      labs(x = "Frame", y = "Absolute velocity (µm/s)") +
      plot_theme()
  })

  output$angle_metrics <- renderUI({
    row <- selected_result()
    if (is.null(row)) return(empty_state("compass", "No result selected", "Run tracking or choose a saved result."))
    summary <- angle_summary()
    layout_columns(
      col_widths = c(3, 3, 3, 3),
      metric_value_box("Dominant direction", paste0(format_metric(summary$circular_mean_deg, 1), "°"), "Circular mean across all steps", "compass", "teal"),
      metric_value_box("Direction stability", format_metric(summary$directional_stability, 2), "0 = dispersed, 1 = aligned", "bullseye", "blue"),
      metric_value_box("Mean absolute turn", paste0(format_metric(summary$mean_absolute_turn_deg, 1), "°"), paste0(summary$reversal_count, " reversal step(s)"), "rotate", "amber"),
      metric_value_box("Motion pattern", summary$pattern, summary$detail, "wave-square", "gray")
    )
  })

  output$motion_angle_plot <- renderPlot({
    data <- angle_trajectory()
    validate(need(nrow(data) > 0, "No angle trajectory data for this result."))
    data <- data[!is.na(data$motion_angle_deg), , drop = FALSE]
    validate(need(nrow(data) > 0, "No non-zero motion steps are available."))
    data$track_id <- factor(data$track_id)
    ggplot(data, aes(x = elapsed_time_s, y = motion_angle_deg, group = track_id, color = track_id)) +
      geom_hline(yintercept = 0, color = "#AAB5B2", linewidth = 0.4) +
      geom_line(linewidth = 0.65, alpha = 0.65) +
      geom_point(size = 1.5) +
      scale_y_continuous(limits = c(-180, 180), breaks = seq(-180, 180, 90)) +
      labs(x = "Elapsed time (s)", y = "Motion angle (degrees)") +
      plot_theme()
  })

  output$turning_angle_plot <- renderPlot({
    data <- angle_trajectory()
    validate(need(nrow(data) > 0, "No angle trajectory data for this result."))
    data <- data[!is.na(data$turning_angle_deg), , drop = FALSE]
    validate(need(nrow(data) > 0, "At least three tracked positions are required to calculate turning."))
    data$track_id <- factor(data$track_id)
    ggplot(data, aes(x = elapsed_time_s, y = turning_angle_deg, group = track_id, color = track_id)) +
      geom_hline(yintercept = 0, color = "#7E8B88", linewidth = 0.45) +
      geom_hline(yintercept = c(-135, 135), color = "#B33A3A", linewidth = 0.35, linetype = "dashed") +
      geom_line(linewidth = 0.65, alpha = 0.7) +
      geom_point(size = 1.5) +
      scale_y_continuous(limits = c(-180, 180), breaks = seq(-180, 180, 90)) +
      labs(x = "Elapsed time (s)", y = "Turning angle (degrees)") +
      plot_theme()
  })

  output$position_time_plot <- renderPlot({
    data <- angle_trajectory()
    validate(need(nrow(data) > 0, "No tracked positions for this result."))
    x_data <- data.frame(
      track_id = data$track_id, elapsed_time_s = data$elapsed_time_s,
      coordinate = "X", position_px = data$x_px
    )
    y_data <- data.frame(
      track_id = data$track_id, elapsed_time_s = data$elapsed_time_s,
      coordinate = "Y", position_px = data$y_px
    )
    position_data <- rbind(x_data, y_data)
    position_data$track_id <- factor(position_data$track_id)
    ggplot(position_data, aes(x = elapsed_time_s, y = position_px, group = track_id, color = track_id)) +
      geom_line(linewidth = 0.7, alpha = 0.75) +
      facet_wrap(~coordinate, scales = "free_y", ncol = 1) +
      labs(x = "Elapsed time (s)", y = "Position (px)") +
      plot_theme()
  })

  output$angle_table <- renderUI({
    data <- angle_trajectory()
    if (nrow(data) == 0) return(empty_state("table", "No angle table", "The selected run has no readable trajectory CSV."))
    div(class = "data-table-wrap trajectory-table-wrap", tableOutput("angle_table_inner"))
  })
  output$angle_table_inner <- renderTable({
    data <- angle_trajectory()
    keep <- intersect(
      c("track_id", "frame_index", "elapsed_time_s", "x_px", "y_px", "motion_angle_deg", "turning_angle_deg", "absolute_velocity_um_per_s"),
      names(data)
    )
    head(data[, keep, drop = FALSE], 250)
  }, striped = TRUE, hover = TRUE, spacing = "s", rownames = FALSE, digits = 3)

  output$download_angle_data <- downloadHandler(
    filename = function() "actintrack_angle_dynamics.csv",
    content = function(file) write.csv(angle_trajectory(), file, row.names = FALSE)
  )

  local_image_ui <- function(path, alt) {
    if (!safe_output_file(path)) return(empty_state("image", "Preview unavailable", "This run does not include the requested QC image."))
    encoded <- base64enc::dataURI(file = path, mime = "image/png")
    tags$img(src = encoded, alt = alt, class = "qc-image")
  }

  output$starting_points_media <- renderUI({
    row <- selected_result()
    if (is.null(row)) return(empty_state("image", "No result selected", "Choose a result to inspect QC imagery."))
    local_image_ui(row$starting_points, "Detected starting points")
  })
  output$track_overlay_media <- renderUI({
    row <- selected_result()
    if (is.null(row)) return(empty_state("image", "No result selected", "Choose a result to inspect QC imagery."))
    local_image_ui(row$track_overlay, "Tracked point paths")
  })
  output$angle_overlay_media <- renderUI({
    row <- selected_result()
    if (is.null(row)) {
      return(empty_state("route", "No result selected", "Choose a tracking result to preview its trajectories."))
    }
    local_image_ui(row$track_overlay, paste("Trajectory overlay for", row$source_name))
  })

  output$trajectory_table <- renderUI({
    data <- trajectory()
    if (nrow(data) == 0) return(empty_state("table", "No trajectory table", "The selected run has no readable CSV output."))
    keep <- intersect(
      c("track_id", "frame_index", "x_px", "y_px", "displacement_um", "absolute_velocity_um_per_s", "downward_velocity_um_per_s", "confidence"),
      names(data)
    )
    div(class = "data-table-wrap trajectory-table-wrap", tableOutput("trajectory_table_inner"))
  })
  output$trajectory_table_inner <- renderTable({
    data <- trajectory()
    keep <- intersect(
      c("track_id", "frame_index", "x_px", "y_px", "displacement_um", "absolute_velocity_um_per_s", "downward_velocity_um_per_s", "confidence"),
      names(data)
    )
    head(data[, keep, drop = FALSE], 250)
  }, striped = TRUE, hover = TRUE, spacing = "s", rownames = FALSE)

  observeEvent(project_dir(), {
    prefix <- "actintrack-processed"
    if (prefix %in% names(resourcePaths())) removeResourcePath(prefix)
    processed <- file.path(project_dir(), "processed")
    if (dir.exists(processed)) addResourcePath(prefix, processed)
  }, ignoreInit = FALSE)

  processed_media_url <- function(path) {
    if (!safe_output_file(path)) return("")
    relative <- relative_to_project(file.path(project_dir(), "processed"), path)
    parts <- strsplit(relative, .Platform$file.sep, fixed = TRUE)[[1]]
    paste0("actintrack-processed/", paste(vapply(parts, URLencode, character(1), reserved = TRUE), collapse = "/"))
  }

  ensure_browser_preview <- function(row) {
    if (is.null(row)) return("")
    if (safe_output_file(row$track_preview_webm)) return(row$track_preview_webm)
    if (!safe_output_file(row$track_preview)) return("")
    target <- row$track_preview_webm %||% sub(
      "\\.mp4$", ".webm", row$track_preview, ignore.case = TRUE
    )
    if (!nzchar(target) || identical(target, row$track_preview)) return("")
    converted <- tryCatch({
      run_bridge(project_dir(), c("browser-preview", row$track_preview, target))
      target
    }, error = function(...) "")
    if (safe_output_file(converted)) converted else ""
  }

  angle_browser_preview <- reactive(ensure_browser_preview(selected_result()))
  result_browser_preview <- reactive(ensure_browser_preview(selected_result()))

  browser_video_ui <- function(row, webm_path, aria_label) {
    sources <- list()
    if (safe_output_file(webm_path)) {
      sources <- c(sources, list(tags$source(
        src = processed_media_url(webm_path),
        type = "video/webm"
      )))
    }
    mp4_codec <- row$track_preview_mp4_codec %||% ""
    if (safe_output_file(row$track_preview) && mp4_codec %in% c("avc1", "H264")) {
      sources <- c(sources, list(tags$source(
        src = processed_media_url(row$track_preview),
        type = "video/mp4"
      )))
    }
    if (length(sources) == 0) return(NULL)
    tags$video(
      sources,
      controls = NA,
      preload = "metadata",
      class = "track-video angle-track-video",
      `aria-label` = aria_label,
      "This browser cannot play the generated preview. Use the trajectory overlay below."
    )
  }

  output$angle_preview_media <- renderUI({
    row <- selected_result()
    if (is.null(row)) {
      return(empty_state("video", "No result selected", "Choose a tracking result to preview the full sequence."))
    }
    video <- browser_video_ui(
      row,
      angle_browser_preview(),
      paste("Full-sequence tracking preview for", row$source_name)
    )
    if (!is.null(video)) return(video)
    if (safe_output_file(row$track_overlay)) {
      return(local_image_ui(row$track_overlay, paste("Trajectory overlay for", row$source_name)))
    }
    empty_state("video-slash", "Preview unavailable", "This saved run has no preview video or trajectory overlay.")
  })

  output$track_video <- renderUI({
    row <- selected_result()
    if (is.null(row)) {
      return(empty_state("video", "Preview video unavailable", "The tracker may not have produced an MP4 preview for this run."))
    }
    video <- browser_video_ui(
      row,
      result_browser_preview(),
      paste("Tracking preview for", row$source_name)
    )
    if (!is.null(video)) return(video)
    empty_state("video-slash", "Preview video unavailable", "No browser-compatible preview could be generated for this run.")
  })

  output$download_trajectory <- downloadHandler(
    filename = function() basename(selected_result()$trajectory_csv %||% "trajectory.csv"),
    content = function(file) file.copy(selected_result()$trajectory_csv, file, overwrite = TRUE)
  )
  output$download_summary <- downloadHandler(
    filename = function() basename(selected_result()$summary_json %||% "summary.json"),
    content = function(file) file.copy(selected_result()$summary_json, file, overwrite = TRUE)
  )

  group_summary <- reactive(summarize_groups(results()))

  output$analysis_metrics <- renderUI({
    summary <- group_summary()
    layout_columns(
      col_widths = c(4, 4, 4),
      metric_value_box("Groups represented", length(unique(results()$group)), "Biological categories", "people-group", "blue"),
      metric_value_box("Completed runs", nrow(results()), "Available for comparison", "flask", "teal"),
      metric_value_box("Valid tracks", format_metric(sum(results()$valid_tracks, na.rm = TRUE), 0), "Across all runs", "route", "amber")
    )
  })

  output$group_plot <- renderPlot({
    summary <- group_summary()
    validate(need(nrow(summary) > 0, "Complete tracking runs to populate group analysis."))
    long <- rbind(
      data.frame(group = summary$group, metric = "Absolute velocity", value = summary$mean_absolute_velocity),
      data.frame(group = summary$group, metric = "Downward velocity", value = summary$mean_downward_velocity)
    )
    ggplot(long, aes(x = group, y = value, fill = metric)) +
      geom_col(position = position_dodge(width = 0.75), width = 0.64) +
      scale_fill_manual(values = c("Absolute velocity" = "#147A6C", "Downward velocity" = "#D08A2E")) +
      labs(x = NULL, y = "Mean velocity (µm/s)") +
      plot_theme() +
      theme(axis.text.x = element_text(angle = 20, hjust = 1))
  })

  output$group_table <- renderUI({
    summary <- group_summary()
    if (nrow(summary) == 0) return(empty_state("chart-column", "No group results", "Complete tracking runs to compare groups."))
    div(class = "data-table-wrap", tableOutput("group_table_inner"))
  })
  output$group_table_inner <- renderTable({
    summary <- group_summary()
    summary$mean_absolute_velocity <- round(summary$mean_absolute_velocity, 4)
    summary$mean_downward_velocity <- round(summary$mean_downward_velocity, 4)
    names(summary) <- c("Group", "Runs", "Absolute µm/s", "Downward µm/s", "Valid tracks", "Valid steps")
    summary
  }, striped = TRUE, hover = TRUE, spacing = "s", rownames = FALSE)

  output$all_results_table <- renderUI({
    data <- results()
    if (nrow(data) == 0) return(empty_state("flask", "No completed runs", "Run tracking to create analysis data."))
    div(class = "data-table-wrap", tableOutput("all_results_table_inner"))
  })
  output$all_results_table_inner <- renderTable({
    data <- results()[, c("group", "source_name", "absolute_velocity", "downward_velocity", "valid_tracks", "valid_steps", "analyzed_at")]
    names(data) <- c("Group", "Source", "Absolute µm/s", "Downward µm/s", "Tracks", "Steps", "Analyzed")
    data
  }, striped = TRUE, hover = TRUE, spacing = "s", rownames = FALSE)

  output$stack_metrics <- renderUI({
    data <- stacks()
    total_size <- if (nrow(data) > 0) sum(data$size_bytes, na.rm = TRUE) else 0
    layout_columns(
      col_widths = c(4, 4, 4),
      metric_value_box("Stack files", nrow(data), "Raw microscopy inputs", "layer-group", "teal"),
      metric_value_box("Total size", format_bytes(total_size), "Local disk footprint", "hard-drive", "blue"),
      metric_value_box("Formats", length(unique(data$extension)), paste(sort(unique(data$extension)), collapse = ", "), "file-waveform", "amber")
    )
  })

  output$stack_table <- renderUI({
    data <- stacks()
    if (nrow(data) == 0) return(empty_state("layer-group", "No z-stacks", "No OIR, OIB, TIFF, or TIF files were found."))
    div(class = "data-table-wrap", tableOutput("stack_table_inner"))
  })
  output$stack_table_inner <- renderTable({
    data <- stacks()[, c("group", "file_name", "extension", "size", "modified", "relative_path")]
    names(data) <- c("Group", "File", "Format", "Size", "Modified", "Location")
    data
  }, striped = TRUE, hover = TRUE, spacing = "s", rownames = FALSE)

  output$stack_selector <- renderUI({
    data <- stacks()
    if (nrow(data) == 0) return(NULL)
    choices <- stats::setNames(data$path, paste(data$group, data$file_name, sep = " / "))
    selectInput("stack_file", "Stack file", choices = choices)
  })
  selected_stack <- reactive({
    req(input$stack_file)
    rows <- stacks()[stacks()$path == input$stack_file, , drop = FALSE]
    if (nrow(rows) == 0) NULL else rows[1, , drop = FALSE]
  })
  output$stack_detail <- renderUI({
    row <- selected_stack()
    if (is.null(row)) return(NULL)
    div(
      class = "stack-detail",
      div(span("Format"), strong(row$extension)),
      div(span("File size"), strong(row$size)),
      div(span("Group"), strong(row$group)),
      div(span("Status"), status_pill("Awaiting metadata extraction", "warning")),
      p(class = "path-text", row$relative_path)
    )
  })

  always_active_outputs <- c(
    "sidebar_workspace_chip", "sidebar_active_source", "workspace_status",
    "source_browser", "source_browser_count", "active_source_banner",
    "source_preview_controls", "source_preview_plot", "source_preview_status",
    "frame_control", "tracking_source_banner", "frame_plot", "preview_status",
    "roi_summary", "run_activity", "result_selector", "review_context_banner",
    "result_metrics", "trajectory_plot", "velocity_plot", "starting_points_media",
    "track_overlay_media", "trajectory_table", "track_video",
    "angle_metrics", "motion_angle_plot", "turning_angle_plot", "position_time_plot",
    "angle_table", "angle_preview_media", "angle_overlay_media"
  )
  for (output_name in always_active_outputs) {
    outputOptions(output, output_name, suspendWhenHidden = FALSE)
  }
}

shinyApp(ui, server)
